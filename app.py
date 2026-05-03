import os
import re
import random
import secrets
import uuid
import hashlib
from datetime import datetime
from flask import (Flask, render_template, redirect, url_for, flash,
                   request, jsonify, abort, session)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from markupsafe import Markup, escape
import markdown2
from models import (db, User, Group, GroupMembership, GroupInvitation,
                    GroupMessage, MessageReaction, DirectMessage,
                    Post, PostReaction, Comment, Follow, Notification)
from config import config
from forms import bot_score, bot_score_label

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}


def allowed_file(filename):
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS)


def save_upload(file):
    """Save an uploaded file and return the stored filename, or None."""
    if not file or not file.filename:
        return None
    if not allowed_file(file.filename):
        return None
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    file.save(os.path.join(UPLOAD_FOLDER, filename))
    return filename


def delete_upload(filename):
    if filename:
        path = os.path.join(UPLOAD_FOLDER, filename)
        if os.path.exists(path):
            os.remove(path)


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])
    app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # 8 MB

    db.init_app(app)

    # Flask-WTF needs a secret key (reuse Flask's)
    if not app.config.get('WTF_CSRF_SECRET_KEY'):
        app.config['WTF_CSRF_SECRET_KEY'] = app.config.get('SECRET_KEY', 'dev')

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = ''

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.after_request
    def add_no_cache_headers(response):
        """Prevent browsers from caching dynamic HTML pages."""
        if 'text/html' in response.content_type:
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    # Inject a static asset version into every template so browsers
    # always load fresh JS/CSS after a deploy (cache-busting).
    import subprocess as _sp
    try:
        _git_hash = _sp.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=os.path.dirname(__file__), stderr=_sp.DEVNULL
        ).decode().strip()
    except Exception:
        _git_hash = '1'

    @app.context_processor
    def inject_static_version():
        return {'static_version': _git_hash}

    @app.before_request
    def update_last_seen():
        # Skip API/polling endpoints — they fire every 2-5s and would cause
        # constant SQLite write-lock contention across all workers.
        if request.path.startswith('/api/'):
            return
        if current_user.is_authenticated:
            now = datetime.utcnow()
            # Only write to DB if last_seen is stale by more than 60 seconds
            if (not current_user.last_seen or
                    (now - current_user.last_seen).total_seconds() > 60):
                current_user.last_seen = now
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

    # ─── Jinja2 filter ───────────────────────────────────────────────────────

    @app.template_filter('linkify')
    def linkify_filter(text):
        """Convert @mentions and #hashtags to clickable links (safe HTML)."""
        if not text:
            return Markup('')
        safe = str(escape(text))
        safe = re.sub(
            r'@([a-zA-Z0-9._]{3,50})',
            r'<a href="/u/\1" class="mention">@\1</a>',
            safe,
        )
        safe = re.sub(
            r'#([a-zA-Z0-9_]{1,50})',
            r'<a href="/tag/\1" class="hashtag">#\1</a>',
            safe,
        )
        return Markup(safe)

    @app.template_filter('md')
    def markdown_filter(text):
        if not text:
            return Markup('')
        safe = str(escape(text))
        rendered = markdown2.markdown(safe, extras=[
            'fenced-code-blocks', 'strike', 'tables',
            'break-on-newline', 'cuddled-lists', 'header-ids',
        ])
        return Markup(rendered)

    # ─── Context Processors ──────────────────────────────────────────────────

    @app.context_processor
    def inject_globals():
        if current_user.is_authenticated:
            unread_notifications = Notification.query.filter_by(
                user_id=current_user.id, is_read=False
            ).count()
            pending_invites = GroupInvitation.query.filter_by(
                invitee_id=current_user.id, status='pending'
            ).count()
            unread_dms = DirectMessage.query.filter_by(
                receiver_id=current_user.id, is_read=False
            ).count()
            my_groups = [
                m.group for m in GroupMembership.query.filter_by(
                    user_id=current_user.id, status='active'
                ).all()
            ]
            return dict(
                unread_notifications=unread_notifications,
                pending_invites=pending_invites,
                unread_dms=unread_dms,
                my_groups=my_groups,
                is_superadmin=current_user.username == 'penguin',
            )
        return dict(unread_notifications=0, pending_invites=0,
                    unread_dms=0, my_groups=[], is_superadmin=False)

    # ─── Auth ─────────────────────────────────────────────────────────────────

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('square'))
        return redirect(url_for('login'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('square'))
        if request.method == 'POST':
            # ── Step 2: captcha answer ──────────────────────────────────────
            if request.form.get('captcha_step'):
                uid = session.get('captcha_uid')
                expected = session.get('captcha_answer')
                try:
                    given = int(request.form.get('captcha_answer', '').strip())
                except ValueError:
                    given = None
                if uid and expected is not None and given == expected:
                    user = User.query.get(uid)
                    if user:
                        user.needs_captcha = False
                        db.session.commit()
                        session.pop('captcha_uid', None)
                        session.pop('captcha_answer', None)
                        remember = session.pop('captcha_remember', False)
                        login_user(user, remember=remember)
                        return redirect(request.args.get('next') or url_for('square'))
                flash('Incorrect answer. Please try again.', 'error')
                # Re-generate challenge
                a, b = random.randint(1, 12), random.randint(1, 12)
                session['captcha_answer'] = a + b
                return render_template('auth/login.html',
                                       captcha_step=True,
                                       captcha_q=f'{a} + {b}')

            # ── Step 1: credential check ────────────────────────────────────
            username = request.form.get('username', '').strip().lower()
            password = request.form.get('password', '')
            remember = request.form.get('remember') == 'on'
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                if user.needs_captcha:
                    a, b = random.randint(1, 12), random.randint(1, 12)
                    session['captcha_uid'] = user.id
                    session['captcha_answer'] = a + b
                    session['captcha_remember'] = remember
                    return render_template('auth/login.html',
                                           captcha_step=True,
                                           captcha_q=f'{a} + {b}')
                login_user(user, remember=remember)
                return redirect(request.args.get('next') or url_for('square'))
            flash('Invalid username or password.', 'error')
        return render_template('auth/login.html')

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('square'))
        if request.method == 'POST':
            username = request.form.get('username', '').strip().lower()
            email = request.form.get('email', '').strip().lower()
            display_name = request.form.get('display_name', '').strip()
            password = request.form.get('password', '')
            confirm = request.form.get('confirm_password', '')

            errors = []
            if not username or len(username) < 3:
                errors.append('Username must be at least 3 characters.')
            if not username.replace('_', '').replace('.', '').isalnum():
                errors.append('Username may only contain letters, numbers, _ and .')
            if not email or '@' not in email:
                errors.append('A valid email is required.')
            if len(password) < 6:
                errors.append('Password must be at least 6 characters.')
            if password != confirm:
                errors.append('Passwords do not match.')
            if User.query.filter_by(username=username).first():
                errors.append('That username is already taken.')
            if User.query.filter_by(email=email).first():
                errors.append('That email is already registered.')

            if errors:
                for err in errors:
                    flash(err, 'error')
            else:
                palette = ['#4F46E5', '#EC4899', '#10B981', '#F59E0B',
                           '#3B82F6', '#8B5CF6', '#EF4444', '#06B6D4',
                           '#14B8A6', '#F97316']
                idx = int(hashlib.md5(username.encode()).hexdigest(), 16) % len(palette)
                user = User(
                    username=username, email=email,
                    display_name=display_name or username,
                    avatar_color=palette[idx],
                )
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                login_user(user)
                flash(f'Welcome to Penguinly, {user.display_name}!', 'success')
                return redirect(url_for('square'))
        return render_template('auth/register.html')

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))

    # ─── Settings ─────────────────────────────────────────────────────────────

    @app.route('/settings', methods=['GET', 'POST'])
    @login_required
    def settings():
        if request.method == 'POST':
            theme = request.form.get('theme', 'sunset')
            if theme not in ('sunset', 'bw', 'natural'):
                theme = 'sunset'
            current_user.theme = theme
            current_user.article_mode = request.form.get('article_mode') == '1'
            db.session.commit()
            flash('Settings saved.', 'success')
        return render_template('settings.html')

    # ─── Public Square ────────────────────────────────────────────────────────

    @app.route('/square')
    @login_required
    def square():
        page = request.args.get('page', 1, type=int)
        per_page = 20
        pagination = Post.query.filter_by(post_type='public').order_by(
            Post.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        posts = pagination.items
        following_ids = [f.following_id for f in Follow.query.filter_by(
            follower_id=current_user.id
        ).all()]
        following_ids.append(current_user.id)
        suggested = User.query.filter(~User.id.in_(following_ids)).limit(6).all()
        return render_template('square.html', posts=posts, suggested=suggested,
                               has_next=pagination.has_next, next_page=page + 1)

    @app.route('/square/post', methods=['POST'])
    @login_required
    def create_post():
        content = request.form.get('content', '').strip()
        is_markdown = request.form.get('is_markdown') == '1'
        image_filename = save_upload(request.files.get('image'))

        if not content and not image_filename:
            flash('Post cannot be empty.', 'error')
            return redirect(url_for('square'))
        if len(content) > 5000:
            flash('Post too long (max 5000 characters).', 'error')
            return redirect(url_for('square'))

        post = Post(
            user_id=current_user.id,
            content=content,
            post_type='public',
            is_markdown=is_markdown,
            image_filename=image_filename,
        )
        db.session.add(post)
        db.session.flush()
        # @mention notifications
        for username in set(re.findall(r'@([a-zA-Z0-9._]{3,50})', content)):
            mentioned = User.query.filter_by(username=username.lower()).first()
            if mentioned and mentioned.id != current_user.id:
                db.session.add(Notification(
                    user_id=mentioned.id, type='mention',
                    message=f'{current_user.display_name} mentioned you in a post.',
                    related_id=post.id,
                ))
        db.session.commit()
        return redirect(url_for('square'))

    @app.route('/post/<int:post_id>/delete', methods=['POST'])
    @login_required
    def delete_post(post_id):
        post = Post.query.get_or_404(post_id)
        if post.user_id != current_user.id and not current_user.is_admin:
            abort(403)
        PostReaction.query.filter_by(post_id=post_id).delete()
        Comment.query.filter_by(post_id=post_id).delete()
        delete_upload(post.image_filename)
        db.session.delete(post)
        db.session.commit()
        return redirect(request.referrer or url_for('square'))

    @app.route('/post/<int:post_id>/react', methods=['POST'])
    @login_required
    def react_post(post_id):
        post = Post.query.get_or_404(post_id)
        rtype = request.form.get('reaction_type', 'like')
        if rtype not in ('like', 'heart'):
            abort(400)
        existing = PostReaction.query.filter_by(
            post_id=post_id, user_id=current_user.id, reaction_type=rtype
        ).first()
        if existing:
            db.session.delete(existing)
        else:
            db.session.add(PostReaction(
                post_id=post_id, user_id=current_user.id, reaction_type=rtype
            ))
            if post.user_id != current_user.id:
                db.session.add(Notification(
                    user_id=post.user_id, type='reaction',
                    message=f'{current_user.display_name} reacted to your post.',
                    related_id=post_id,
                ))
        db.session.commit()
        return redirect(request.referrer or url_for('square'))

    @app.route('/post/<int:post_id>/comment', methods=['POST'])
    @login_required
    def comment_post(post_id):
        post = Post.query.get_or_404(post_id)
        content = request.form.get('content', '').strip()
        if content:
            comment = Comment(
                post_id=post_id, user_id=current_user.id, content=content
            )
            db.session.add(comment)
            if post.user_id != current_user.id:
                db.session.add(Notification(
                    user_id=post.user_id, type='comment',
                    message=f'{current_user.display_name} commented on your post.',
                    related_id=post_id,
                ))
            # @mention notifications in comment
            for username in set(re.findall(r'@([a-zA-Z0-9._]{3,50})', content)):
                mentioned = User.query.filter_by(username=username.lower()).first()
                if mentioned and mentioned.id != current_user.id and mentioned.id != post.user_id:
                    db.session.add(Notification(
                        user_id=mentioned.id, type='mention',
                        message=f'{current_user.display_name} mentioned you in a comment.',
                        related_id=post_id,
                    ))
            db.session.commit()
        return redirect(request.referrer or url_for('square'))

    @app.route('/comment/<int:comment_id>/edit', methods=['POST'])
    @login_required
    def edit_comment(comment_id):
        comment = Comment.query.get_or_404(comment_id)
        if comment.user_id != current_user.id:
            abort(403)
        content = request.form.get('content', '').strip()
        if content:
            comment.content = content
            comment.updated_at = datetime.utcnow()
            db.session.commit()
        return redirect(request.referrer or url_for('square'))

    @app.route('/comment/<int:comment_id>/delete', methods=['POST'])
    @login_required
    def delete_comment(comment_id):
        comment = Comment.query.get_or_404(comment_id)
        if comment.user_id != current_user.id and not current_user.is_admin:
            abort(403)
        db.session.delete(comment)
        db.session.commit()
        return redirect(request.referrer or url_for('square'))

    @app.route('/follow/<int:user_id>', methods=['POST'])
    @login_required
    def follow_user(user_id):
        if user_id == current_user.id:
            abort(400)
        User.query.get_or_404(user_id)
        existing = Follow.query.filter_by(
            follower_id=current_user.id, following_id=user_id
        ).first()
        if existing:
            db.session.delete(existing)
        else:
            db.session.add(Follow(follower_id=current_user.id, following_id=user_id))
            db.session.add(Notification(
                user_id=user_id, type='follow',
                message=f'{current_user.display_name} started following you.',
                related_id=current_user.id,
            ))
        db.session.commit()
        return redirect(request.referrer or url_for('square'))

    # ─── Groups ───────────────────────────────────────────────────────────────

    @app.route('/groups')
    @login_required
    def groups():
        my_memberships = GroupMembership.query.filter_by(
            user_id=current_user.id, status='active'
        ).all()
        my_groups = [m.group for m in my_memberships]
        group_invites = GroupInvitation.query.filter_by(
            invitee_id=current_user.id, status='pending'
        ).all()
        return render_template('groups/index.html',
                               my_groups=my_groups,
                               group_invites=group_invites)

    @app.route('/groups/create', methods=['GET', 'POST'])
    @login_required
    def create_group():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            cover_color = request.form.get('cover_color', '#4F46E5')
            is_private = request.form.get('is_private') != 'off'
            if not name:
                flash('Group name is required.', 'error')
                return render_template('groups/create.html')
            group = Group(
                name=name, description=description,
                created_by=current_user.id,
                cover_color=cover_color, is_private=is_private,
            )
            db.session.add(group)
            db.session.flush()
            db.session.add(GroupMembership(
                group_id=group.id, user_id=current_user.id,
                role='admin', status='active',
            ))
            db.session.commit()
            flash(f'"{name}" is live!', 'success')
            return redirect(url_for('view_group', group_id=group.id))
        return render_template('groups/create.html')

    @app.route('/groups/<int:group_id>')
    @login_required
    def view_group(group_id):
        group = Group.query.get_or_404(group_id)
        if not group.is_member(current_user):
            flash('You are not a member of this group.', 'error')
            return redirect(url_for('groups'))
        messages = GroupMessage.query.filter_by(group_id=group_id).order_by(
            GroupMessage.created_at.asc()
        ).all()
        members = GroupMembership.query.filter_by(
            group_id=group_id, status='active'
        ).all()
        is_admin = group.is_admin(current_user)
        member_ids = [m.user_id for m in members]
        pending_ids = [i.invitee_id for i in GroupInvitation.query.filter_by(
            group_id=group_id, status='pending'
        ).all()]
        exclude_ids = list(set(member_ids + pending_ids))
        invitable = User.query.filter(~User.id.in_(exclude_ids)).all() if is_admin else []
        return render_template('groups/view.html',
                               group=group, messages=messages,
                               members=members, is_admin=is_admin,
                               invitable_users=invitable)

    @app.route('/groups/<int:group_id>/message', methods=['POST'])
    @login_required
    def send_group_message(group_id):
        group = Group.query.get_or_404(group_id)
        if not group.is_member(current_user):
            abort(403)
        content = request.form.get('content', '').strip()
        if content:
            db.session.add(GroupMessage(
                group_id=group_id, user_id=current_user.id, content=content
            ))
            db.session.commit()
        return redirect(url_for('view_group', group_id=group_id))

    @app.route('/groups/<int:group_id>/message/<int:message_id>/delete', methods=['POST'])
    @login_required
    def delete_group_message(group_id, message_id):
        group = Group.query.get_or_404(group_id)
        msg = GroupMessage.query.get_or_404(message_id)
        if msg.user_id != current_user.id and not group.is_admin(current_user):
            abort(403)
        MessageReaction.query.filter_by(message_id=message_id).delete()
        db.session.delete(msg)
        db.session.commit()
        return redirect(url_for('view_group', group_id=group_id))

    @app.route('/groups/<int:group_id>/invite', methods=['POST'])
    @login_required
    def invite_to_group(group_id):
        group = Group.query.get_or_404(group_id)
        if not group.is_admin(current_user):
            abort(403)
        if not group.can_join():
            flash('Group is at maximum capacity.', 'error')
            return redirect(url_for('view_group', group_id=group_id))
        invitee_id = request.form.get('user_id', type=int)
        invitee = User.query.get_or_404(invitee_id)
        existing = GroupInvitation.query.filter_by(
            group_id=group_id, invitee_id=invitee_id, status='pending'
        ).first()
        if existing:
            flash(f'{invitee.display_name} already has a pending invitation.', 'warning')
            return redirect(url_for('view_group', group_id=group_id))
        invite = GroupInvitation(
            group_id=group_id, inviter_id=current_user.id, invitee_id=invitee_id
        )
        db.session.add(invite)
        db.session.add(Notification(
            user_id=invitee_id, type='invite',
            message=f'{current_user.display_name} invited you to join "{group.name}".',
            related_id=group_id,
        ))
        db.session.commit()
        flash(f'Invitation sent to {invitee.display_name}.', 'success')
        return redirect(url_for('view_group', group_id=group_id))

    @app.route('/invitations/<int:invite_id>/respond', methods=['POST'])
    @login_required
    def respond_invitation(invite_id):
        inv = GroupInvitation.query.get_or_404(invite_id)
        if inv.invitee_id != current_user.id:
            abort(403)
        if inv.status != 'pending':
            flash('This invitation has already been handled.', 'warning')
            return redirect(url_for('groups'))
        inv.responded_at = datetime.utcnow()
        if request.form.get('action') == 'accept':
            inv.status = 'accepted'
            existing = GroupMembership.query.filter_by(
                group_id=inv.group_id, user_id=current_user.id
            ).first()
            if not existing:
                db.session.add(GroupMembership(
                    group_id=inv.group_id, user_id=current_user.id,
                    role='member', status='active',
                ))
            db.session.commit()
            flash(f'You joined "{inv.group.name}"!', 'success')
            return redirect(url_for('view_group', group_id=inv.group_id))
        else:
            inv.status = 'rejected'
            db.session.commit()
            flash('Invitation declined.', 'info')
        return redirect(url_for('groups'))

    @app.route('/groups/<int:group_id>/members/<int:user_id>/remove', methods=['POST'])
    @login_required
    def remove_group_member(group_id, user_id):
        group = Group.query.get_or_404(group_id)
        if not group.is_admin(current_user):
            abort(403)
        if user_id == current_user.id:
            flash('You cannot remove yourself.', 'error')
            return redirect(url_for('view_group', group_id=group_id))
        membership = GroupMembership.query.filter_by(
            group_id=group_id, user_id=user_id, status='active'
        ).first_or_404()
        membership.status = 'removed'
        db.session.commit()
        flash('Member removed.', 'info')
        return redirect(url_for('view_group', group_id=group_id))

    @app.route('/groups/<int:group_id>/leave', methods=['POST'])
    @login_required
    def leave_group(group_id):
        group = Group.query.get_or_404(group_id)
        membership = GroupMembership.query.filter_by(
            group_id=group_id, user_id=current_user.id, status='active'
        ).first_or_404()
        admin_count = GroupMembership.query.filter_by(
            group_id=group_id, status='active', role='admin'
        ).count()
        if group.is_admin(current_user) and admin_count == 1:
            flash('Transfer admin to another member before leaving.', 'error')
            return redirect(url_for('view_group', group_id=group_id))
        membership.status = 'left'
        db.session.commit()
        flash(f'You left "{group.name}".', 'info')
        return redirect(url_for('groups'))

    @app.route('/groups/<int:group_id>/react/<int:message_id>', methods=['POST'])
    @login_required
    def react_message(group_id, message_id):
        group = Group.query.get_or_404(group_id)
        if not group.is_member(current_user):
            abort(403)
        GroupMessage.query.get_or_404(message_id)
        rtype = request.form.get('reaction_type', 'like')
        if rtype not in ('like', 'heart'):
            abort(400)
        existing = MessageReaction.query.filter_by(
            message_id=message_id, user_id=current_user.id, reaction_type=rtype
        ).first()
        if existing:
            db.session.delete(existing)
        else:
            db.session.add(MessageReaction(
                message_id=message_id, user_id=current_user.id, reaction_type=rtype
            ))
        db.session.commit()
        return redirect(url_for('view_group', group_id=group_id))

    # ─── Direct Messages ──────────────────────────────────────────────────────

    @app.route('/dm')
    @login_required
    def dm_list():
        convos, all_users = _get_dm_data(None)
        return render_template('dm/index.html', conversations=convos,
                               all_users=all_users, active_user=None, messages=[])

    @app.route('/dm/<int:user_id>')
    @login_required
    def dm_chat(user_id):
        other = User.query.get_or_404(user_id)
        if other.id == current_user.id:
            return redirect(url_for('dm_list'))
        DirectMessage.query.filter_by(
            sender_id=user_id, receiver_id=current_user.id, is_read=False
        ).update({'is_read': True})
        db.session.commit()
        messages = DirectMessage.query.filter(
            db.or_(
                db.and_(DirectMessage.sender_id == current_user.id,
                        DirectMessage.receiver_id == user_id),
                db.and_(DirectMessage.sender_id == user_id,
                        DirectMessage.receiver_id == current_user.id),
            )
        ).order_by(DirectMessage.created_at.asc()).all()
        convos, all_users = _get_dm_data(user_id)
        return render_template('dm/index.html', conversations=convos,
                               all_users=all_users, active_user=other,
                               messages=messages)

    def _get_dm_data(include_user_id):
        sent_to = db.session.query(DirectMessage.receiver_id).filter_by(
            sender_id=current_user.id
        ).distinct()
        recv_from = db.session.query(DirectMessage.sender_id).filter_by(
            receiver_id=current_user.id
        ).distinct()
        uids = set()
        for r in sent_to:
            uids.add(r[0])
        for r in recv_from:
            uids.add(r[0])
        uids.discard(current_user.id)
        if include_user_id:
            uids.add(include_user_id)
        convos = []
        for uid in uids:
            u = User.query.get(uid)
            if not u:
                continue
            last = DirectMessage.query.filter(
                db.or_(
                    db.and_(DirectMessage.sender_id == current_user.id,
                            DirectMessage.receiver_id == uid),
                    db.and_(DirectMessage.sender_id == uid,
                            DirectMessage.receiver_id == current_user.id),
                )
            ).order_by(DirectMessage.created_at.desc()).first()
            unread = DirectMessage.query.filter_by(
                sender_id=uid, receiver_id=current_user.id, is_read=False
            ).count()
            convos.append({'user': u, 'last_message': last, 'unread_count': unread})
        convos.sort(
            key=lambda x: x['last_message'].created_at if x['last_message'] else datetime.min,
            reverse=True,
        )
        return convos, User.query.filter(User.id != current_user.id).all()

    @app.route('/dm/<int:user_id>/send', methods=['POST'])
    @login_required
    def send_dm(user_id):
        User.query.get_or_404(user_id)
        content = request.form.get('content', '').strip()
        if content:
            db.session.add(DirectMessage(
                sender_id=current_user.id, receiver_id=user_id, content=content
            ))
            db.session.add(Notification(
                user_id=user_id, type='dm',
                message=f'{current_user.display_name} sent you a message.',
                related_id=current_user.id,
            ))
            db.session.commit()
        return redirect(url_for('dm_chat', user_id=user_id))

    # ─── Profile ──────────────────────────────────────────────────────────────

    @app.route('/profile/<username>')
    @login_required
    def profile(username):
        user = User.query.filter_by(username=username).first_or_404()
        posts = Post.query.filter_by(user_id=user.id, post_type='public').order_by(
            Post.created_at.desc()
        ).all()
        return render_template('profile/view.html', user=user, posts=posts,
                               is_following=current_user.is_following(user))

    @app.route('/profile/edit', methods=['GET', 'POST'])
    @login_required
    def edit_profile():
        if request.method == 'POST':
            display_name = request.form.get('display_name', '').strip()
            bio = request.form.get('bio', '').strip()
            avatar_color = request.form.get('avatar_color', current_user.avatar_color)
            current_user.display_name = display_name or current_user.username
            current_user.bio = bio[:200] if bio else None
            if avatar_color.startswith('#') and len(avatar_color) == 7:
                current_user.avatar_color = avatar_color
            db.session.commit()
            flash('Profile updated!', 'success')
            return redirect(url_for('profile', username=current_user.username))
        return render_template('profile/edit.html')

    # ─── @mention shorthand URL ───────────────────────────────────────────────

    @app.route('/u/<username>')
    @login_required
    def mention_redirect(username):
        return redirect(url_for('profile', username=username))

    # ─── #Hashtag page ────────────────────────────────────────────────────────

    @app.route('/tag/<tag>')
    @login_required
    def hashtag(tag):
        tag_clean = re.sub(r'[^a-zA-Z0-9_]', '', tag).lower()
        posts = Post.query.filter(
            Post.content.ilike(f'%#{tag_clean}%'),
            Post.post_type == 'public',
        ).order_by(Post.created_at.desc()).all()
        return render_template('tag.html', tag=tag_clean, posts=posts)

    # ─── Notifications ────────────────────────────────────────────────────────

    @app.route('/notifications')
    @login_required
    def notifications():
        notifs = Notification.query.filter_by(
            user_id=current_user.id
        ).order_by(Notification.created_at.desc()).limit(50).all()
        Notification.query.filter_by(
            user_id=current_user.id, is_read=False
        ).update({'is_read': True})
        db.session.commit()
        return render_template('notifications.html', notifications=notifs)

    # ─── JSON API ─────────────────────────────────────────────────────────────

    @app.route('/api/groups/<int:group_id>/messages')
    @login_required
    def api_group_messages(group_id):
        group = Group.query.get_or_404(group_id)
        if not group.is_member(current_user):
            abort(403)
        after_id = request.args.get('after', 0, type=int)
        msgs = GroupMessage.query.filter(
            GroupMessage.group_id == group_id,
            GroupMessage.id > after_id,
        ).order_by(GroupMessage.created_at.asc()).all()
        return jsonify([{
            'id': m.id,
            'content': m.content,
            'user_id': m.user_id,
            'display_name': m.author.display_name,
            'avatar_color': m.author.avatar_color,
            'initials': m.author.get_avatar_initials(),
            'created_at': m.created_at.strftime('%H:%M'),
            'is_own': m.user_id == current_user.id,
            'likes': MessageReaction.query.filter_by(
                message_id=m.id, reaction_type='like').count(),
            'hearts': MessageReaction.query.filter_by(
                message_id=m.id, reaction_type='heart').count(),
        } for m in msgs])

    @app.route('/api/dm/<int:user_id>/messages')
    @login_required
    def api_dm_messages(user_id):
        after_id = request.args.get('after', 0, type=int)
        msgs = DirectMessage.query.filter(
            db.or_(
                db.and_(DirectMessage.sender_id == current_user.id,
                        DirectMessage.receiver_id == user_id),
                db.and_(DirectMessage.sender_id == user_id,
                        DirectMessage.receiver_id == current_user.id),
            ),
            DirectMessage.id > after_id,
        ).order_by(DirectMessage.created_at.asc()).all()
        DirectMessage.query.filter_by(
            sender_id=user_id, receiver_id=current_user.id, is_read=False
        ).update({'is_read': True})
        db.session.commit()
        return jsonify([{
            'id': m.id,
            'content': m.content,
            'is_own': m.sender_id == current_user.id,
            'created_at': m.created_at.strftime('%H:%M'),
        } for m in msgs])

    @app.route('/api/users/search')
    @login_required
    def api_users_search():
        q = request.args.get('q', '').strip().lower()
        if not q:
            return jsonify([])
        users = User.query.filter(
            User.username.ilike(f'{q}%')
        ).limit(8).all()
        return jsonify([{
            'username': u.username,
            'display_name': u.display_name,
            'avatar_color': u.avatar_color,
            'initials': u.get_avatar_initials(),
        } for u in users])

    @app.route('/api/hashtags/search')
    @login_required
    def api_hashtags_search():
        q = request.args.get('q', '').strip().lower()
        if not q:
            return jsonify([])
        recent = Post.query.filter(
            Post.content.ilike(f'%#{q}%')
        ).order_by(Post.created_at.desc()).limit(100).all()
        tags = set()
        for post in recent:
            for match in re.findall(r'#([a-zA-Z0-9_]{1,50})', post.content):
                if match.lower().startswith(q):
                    tags.add(match.lower())
        return jsonify(sorted(list(tags))[:8])

    @app.route('/api/badge-counts')
    @login_required
    def api_badge_counts():
        return jsonify({
            'notifications': Notification.query.filter_by(
                user_id=current_user.id, is_read=False).count(),
            'dms': DirectMessage.query.filter_by(
                receiver_id=current_user.id, is_read=False).count(),
            'invites': GroupInvitation.query.filter_by(
                invitee_id=current_user.id, status='pending').count(),
        })

    # ─── Superadmin (username == 'penguin') ──────────────────────────────────

    def require_superadmin():
        if not current_user.is_authenticated or current_user.username != 'penguin':
            abort(403)

    @app.route('/admin')
    @login_required
    def admin_panel():
        require_superadmin()
        users = User.query.order_by(User.created_at.desc()).all()
        scored = []
        for u in users:
            sc = bot_score(u.username)
            label, cls = bot_score_label(sc)
            scored.append({'user': u, 'score': sc, 'label': label, 'cls': cls})
        return render_template('admin/panel.html', scored=scored)

    @app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
    @login_required
    def admin_delete_user(user_id):
        require_superadmin()
        user = User.query.get_or_404(user_id)
        if user.username == 'penguin':
            flash("Can't delete the superadmin account.", 'error')
            return redirect(url_for('admin_panel'))
        # Cascade-delete owned data
        # 1. Groups this user created — delete their contents first, then the group
        owned_groups = Group.query.filter_by(created_by=user_id).all()
        for group in owned_groups:
            gid = group.id
            for msg in GroupMessage.query.filter_by(group_id=gid).all():
                MessageReaction.query.filter_by(message_id=msg.id).delete()
            GroupMessage.query.filter_by(group_id=gid).delete()
            GroupMembership.query.filter_by(group_id=gid).delete()
            GroupInvitation.query.filter_by(group_id=gid).delete()
            db.session.delete(group)
        db.session.flush()  # resolve group FK before deleting user

        # 2. Posts and their reactions/comments
        for post in Post.query.filter_by(user_id=user_id).all():
            PostReaction.query.filter_by(post_id=post.id).delete()
            Comment.query.filter_by(post_id=post.id).delete()
        Post.query.filter_by(user_id=user_id).delete()

        # 3. Comments on other people's posts
        Comment.query.filter_by(user_id=user_id).delete()

        # 4. DMs, notifications, follows, remaining memberships/invitations, reactions
        DirectMessage.query.filter(
            (DirectMessage.sender_id == user_id) |
            (DirectMessage.receiver_id == user_id)
        ).delete()
        Notification.query.filter_by(user_id=user_id).delete()
        Follow.query.filter(
            (Follow.follower_id == user_id) |
            (Follow.following_id == user_id)
        ).delete()
        GroupMembership.query.filter_by(user_id=user_id).delete()
        GroupInvitation.query.filter(
            (GroupInvitation.inviter_id == user_id) |
            (GroupInvitation.invitee_id == user_id)
        ).delete()
        PostReaction.query.filter_by(user_id=user_id).delete()
        MessageReaction.query.filter_by(user_id=user_id).delete()

        db.session.delete(user)
        db.session.commit()
        flash(f'User @{user.username} deleted.', 'success')
        return redirect(url_for('admin_panel'))

    @app.route('/admin/user/<int:user_id>/reset-password', methods=['POST'])
    @login_required
    def admin_reset_password(user_id):
        require_superadmin()
        user = User.query.get_or_404(user_id)
        temp = secrets.token_urlsafe(10)
        user.set_password(temp)
        db.session.commit()
        flash(f'Password for @{user.username} reset to: {temp}  (shown once)', 'success')
        return redirect(url_for('admin_panel'))

    @app.route('/admin/user/<int:user_id>/captcha', methods=['POST'])
    @login_required
    def admin_send_captcha(user_id):
        require_superadmin()
        user = User.query.get_or_404(user_id)
        user.needs_captcha = True
        db.session.commit()
        flash(f'@{user.username} will be challenged on next login.', 'success')
        return redirect(url_for('admin_panel'))

    @app.route('/admin/user/<int:user_id>/unban', methods=['POST'])
    @login_required
    def admin_unban_user(user_id):
        require_superadmin()
        user = User.query.get_or_404(user_id)
        user.is_banned = False
        user.needs_captcha = False
        db.session.commit()
        flash(f'@{user.username} cleared.', 'success')
        return redirect(url_for('admin_panel'))

    @app.route('/admin/user/<int:user_id>/ban', methods=['POST'])
    @login_required
    def admin_ban_user(user_id):
        require_superadmin()
        user = User.query.get_or_404(user_id)
        if user.username == 'penguin':
            flash("Can't ban the superadmin.", 'error')
            return redirect(url_for('admin_panel'))
        user.is_banned = True
        db.session.commit()
        flash(f'@{user.username} banned.', 'success')
        return redirect(url_for('admin_panel'))

    # Enforce ban + captcha on login
    @app.before_request
    def check_ban():
        if current_user.is_authenticated and current_user.is_banned:
            logout_user()
            flash('Your account has been suspended.', 'error')
            return redirect(url_for('login'))

    # ─── CLI Commands ─────────────────────────────────────────────────────────

    @app.cli.command('init-db')
    def init_db_cmd():
        db.create_all()
        print('Database initialised.')

    @app.cli.command('migrate-db')
    def migrate_db_cmd():
        """Add new columns to existing database."""
        with db.engine.connect() as conn:
            migrations = [
                "ALTER TABLE users ADD COLUMN theme VARCHAR(20) DEFAULT 'sunset'",
                "ALTER TABLE users ADD COLUMN article_mode BOOLEAN DEFAULT 0",
                "ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0",
                "ALTER TABLE posts ADD COLUMN image_filename VARCHAR(255)",
                "ALTER TABLE posts ADD COLUMN is_markdown BOOLEAN DEFAULT 0",
                "ALTER TABLE comments ADD COLUMN updated_at DATETIME",
                "ALTER TABLE users ADD COLUMN needs_captcha BOOLEAN DEFAULT 0",
                "ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT 0",
            ]
            for sql in migrations:
                try:
                    conn.execute(db.text(sql))
                    conn.commit()
                    print(f'OK: {sql[:60]}')
                except Exception as e:
                    print(f'SKIP (already exists?): {e}')
        print('Migration complete.')

    @app.cli.command('seed-db')
    def seed_db_cmd():
        demo = [
            ('alice', 'alice@penguinly.app', 'Alice Chen', '#4F46E5', 'Designer & thinker.'),
            ('bob', 'bob@penguinly.app', 'Bob Rivers', '#EC4899', 'Tech & coffee.'),
            ('charlie', 'charlie@penguinly.app', 'Charlie Park', '#10B981', 'Builder.'),
        ]
        for uname, email, dname, color, bio in demo:
            if not User.query.filter_by(username=uname).first():
                u = User(username=uname, email=email, display_name=dname,
                         avatar_color=color, bio=bio)
                u.set_password('password123')
                db.session.add(u)
        db.session.commit()
        print('Seeded.')

    return app


app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)
