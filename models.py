from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    display_name = db.Column(db.String(100))
    bio = db.Column(db.Text)
    avatar_color = db.Column(db.String(7), default='#4F46E5')
    theme = db.Column(db.String(20), default='sunset')          # sunset | bw | natural
    article_mode = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)

    posts = db.relationship('Post', backref='author', lazy='dynamic',
                            foreign_keys='Post.user_id')
    sent_messages = db.relationship('DirectMessage', backref='sender', lazy='dynamic',
                                    foreign_keys='DirectMessage.sender_id')
    received_messages = db.relationship('DirectMessage', backref='receiver', lazy='dynamic',
                                        foreign_keys='DirectMessage.receiver_id')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_avatar_initials(self):
        name = self.display_name or self.username
        parts = name.split()
        if len(parts) >= 2:
            return parts[0][0].upper() + parts[1][0].upper()
        return name[:2].upper()

    def is_following(self, user):
        return Follow.query.filter_by(
            follower_id=self.id, following_id=user.id
        ).first() is not None

    def followers_count(self):
        return Follow.query.filter_by(following_id=self.id).count()

    def following_count(self):
        return Follow.query.filter_by(follower_id=self.id).count()

    def is_online(self):
        if not self.last_seen:
            return False
        return (datetime.utcnow() - self.last_seen).total_seconds() < 300


class Follow(db.Model):
    __tablename__ = 'follows'
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    following_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    follower = db.relationship('User', foreign_keys=[follower_id], backref='following_rel')
    following = db.relationship('User', foreign_keys=[following_id], backref='followers_rel')

    __table_args__ = (db.UniqueConstraint('follower_id', 'following_id'),)


class Group(db.Model):
    __tablename__ = 'groups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    max_members = db.Column(db.Integer, default=19)
    cover_color = db.Column(db.String(7), default='#4F46E5')
    is_private = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', backref='created_groups', foreign_keys=[created_by])
    members = db.relationship('GroupMembership', backref='group', lazy='dynamic')
    messages = db.relationship('GroupMessage', backref='group', lazy='dynamic',
                               order_by='GroupMessage.created_at')
    invitations = db.relationship('GroupInvitation', backref='group', lazy='dynamic')

    def get_active_members(self):
        return GroupMembership.query.filter_by(group_id=self.id, status='active').all()

    def member_count(self):
        return GroupMembership.query.filter_by(group_id=self.id, status='active').count()

    def is_member(self, user):
        return GroupMembership.query.filter_by(
            group_id=self.id, user_id=user.id, status='active'
        ).first() is not None

    def is_admin(self, user):
        m = GroupMembership.query.filter_by(
            group_id=self.id, user_id=user.id, status='active'
        ).first()
        return m and m.role == 'admin'

    def can_join(self):
        return self.member_count() < self.max_members


class GroupMembership(db.Model):
    __tablename__ = 'group_memberships'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(20), default='member')
    status = db.Column(db.String(20), default='active')
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='group_memberships')

    __table_args__ = (db.UniqueConstraint('group_id', 'user_id'),)


class GroupInvitation(db.Model):
    __tablename__ = 'group_invitations'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    inviter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    invitee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    responded_at = db.Column(db.DateTime)

    inviter = db.relationship('User', foreign_keys=[inviter_id], backref='sent_invitations')
    invitee = db.relationship('User', foreign_keys=[invitee_id], backref='received_invitations')


class GroupMessage(db.Model):
    __tablename__ = 'group_messages'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship('User', backref='group_messages')
    reactions = db.relationship('MessageReaction', backref='message', lazy='dynamic')

    def reaction_counts(self):
        likes = MessageReaction.query.filter_by(
            message_id=self.id, reaction_type='like'
        ).count()
        hearts = MessageReaction.query.filter_by(
            message_id=self.id, reaction_type='heart'
        ).count()
        return {'like': likes, 'heart': hearts}


class MessageReaction(db.Model):
    __tablename__ = 'message_reactions'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('group_messages.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reaction_type = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('message_id', 'user_id', 'reaction_type'),)


class DirectMessage(db.Model):
    __tablename__ = 'direct_messages'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Post(db.Model):
    __tablename__ = 'posts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False, default='')
    post_type = db.Column(db.String(20), default='public')
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=True)
    image_filename = db.Column(db.String(255), nullable=True)
    is_markdown = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    reactions = db.relationship('PostReaction', backref='post', lazy='dynamic')
    comments = db.relationship('Comment', backref='post', lazy='dynamic',
                               order_by='Comment.created_at')

    def like_count(self):
        return PostReaction.query.filter_by(
            post_id=self.id, reaction_type='like'
        ).count()

    def heart_count(self):
        return PostReaction.query.filter_by(
            post_id=self.id, reaction_type='heart'
        ).count()

    def comment_count(self):
        return Comment.query.filter_by(post_id=self.id).count()

    def user_reaction(self, user_id):
        return PostReaction.query.filter_by(
            post_id=self.id, user_id=user_id
        ).first()


class PostReaction(db.Model):
    __tablename__ = 'post_reactions'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reaction_type = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='post_reactions')

    __table_args__ = (db.UniqueConstraint('post_id', 'user_id', 'reaction_type'),)


class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True)

    author = db.relationship('User', backref='comments')


class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=False)
    related_id = db.Column(db.Integer)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='notifications')
