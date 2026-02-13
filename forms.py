from wtforms import Form, StringField, PasswordField, SelectField, FloatField, SelectMultipleField
from wtforms.validators import DataRequired, Email, Length, Optional

SKILL_CHOICES = ["喂药", "洗澡", "陪伴", "翻身", "康复训练", "测血压", "测血糖"]


class LoginForm(Form):
    email = StringField(validators=[DataRequired(), Email()])
    password = PasswordField(validators=[DataRequired()])


class RegisterForm(Form):
    role = SelectField(choices=[("worker","护工"),("elder","老人"),("family","家属")], validators=[DataRequired()])
    name = StringField(validators=[DataRequired(), Length(min=2, max=32)])
    email = StringField(validators=[DataRequired(), Email()])
    phone = StringField(validators=[Optional(), Length(max=32)])
    password = PasswordField(validators=[DataRequired(), Length(min=4)])
    price_per_hour = FloatField(validators=[Optional()])
    skills = SelectMultipleField(choices=[(s,s) for s in SKILL_CHOICES], validators=[Optional()])
