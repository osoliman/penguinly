"""
Flask-WTF forms with bot-username detection for Penguinly.
"""
import re
import math
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Regexp, ValidationError

# ─── Bot-username heuristics ─────────────────────────────────────────────────

# Patterns that look machine-generated
_BOT_PATTERNS = [
    re.compile(r'^(user|bot|test|spam|fake|temp|auto|random|account)\d{3,}', re.I),
    re.compile(r'^[a-z]{2,5}\d{6,}$', re.I),          # xk923847
    re.compile(r'^\d{6,}$'),                             # pure numbers
    re.compile(r'^[a-z0-9]{20,}$', re.I),              # very long random string
    re.compile(r'(.)\1{4,}'),                            # aaaaa or 11111
    re.compile(r'^(guest|visitor|member|player|ninja|shadow)\d+', re.I),
]

_SUSPICIOUS_WORDS = {
    'spammer', 'spambot', 'botnet', 'crawler', 'scraper',
    'phishing', 'scammer', 'hacker',
}


def _char_entropy(s: str) -> float:
    """Shannon entropy of a string; higher = more random-looking."""
    if not s:
        return 0.0
    freq = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    total = len(s)
    return -sum((v / total) * math.log2(v / total) for v in freq.values())


def bot_score(username: str) -> int:
    """
    Return 0–100 indicating how likely the username is bot-generated.
    ≥70 = strong suspicion, 40–69 = moderate, <40 = probably human.
    """
    if not username:
        return 0
    score = 0
    u = username.lower()

    # Pattern matches
    for pat in _BOT_PATTERNS:
        if pat.search(u):
            score += 30
            break

    # Suspicious words
    for word in _SUSPICIOUS_WORDS:
        if word in u:
            score += 40
            break

    # High entropy relative to length (random-looking)
    entropy = _char_entropy(u)
    if len(u) >= 8 and entropy > 3.5:
        score += 20

    # Ends with 4+ digits
    if re.search(r'\d{4,}$', u):
        score += 15

    # More than 50% digits
    digit_ratio = sum(1 for c in u if c.isdigit()) / max(len(u), 1)
    if digit_ratio > 0.5:
        score += 15

    # Very long
    if len(u) > 24:
        score += 10

    # No vowels at all (consonant soup)
    if len(u) >= 6 and not any(c in 'aeiou' for c in u):
        score += 20

    return min(score, 100)


def bot_score_label(score: int) -> tuple[str, str]:
    """Return (label, css_class) for a bot score."""
    if score >= 70:
        return 'High risk', 'danger'
    if score >= 40:
        return 'Suspicious', 'warning'
    return 'Clean', 'success'


# ─── WTForms validators ───────────────────────────────────────────────────────

class NotBotUsername:
    """WTForms validator that rejects obvious bot usernames at signup."""
    def __init__(self, threshold=70, message=None):
        self.threshold = threshold
        self.message = message or 'That username looks automated. Please choose a real name.'

    def __call__(self, form, field):
        if bot_score(field.data or '') >= self.threshold:
            raise ValidationError(self.message)


# ─── Forms ────────────────────────────────────────────────────────────────────

class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[
        DataRequired(),
        Length(3, 50),
        Regexp(r'^[a-zA-Z0-9._]+$', message='Only letters, numbers, _ and . allowed.'),
        NotBotUsername(threshold=70),
    ])
    display_name = StringField('Display name', validators=[Length(0, 100)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(6, 128)])
    confirm_password = PasswordField('Confirm password', validators=[DataRequired()])
    remember = BooleanField('Keep me signed in')


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Keep me signed in')


class PostForm(FlaskForm):
    content = TextAreaField('Content', validators=[Length(0, 5000)])


class CommentForm(FlaskForm):
    content = StringField('Comment', validators=[DataRequired(), Length(1, 1000)])
