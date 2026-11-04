from django.db import migrations

# Parol: Beruniy2026!Admin — faqat hash saqlanadi.
# Birinchi kirishdan keyin Settings orqali almashtirish tavsiya etiladi.
ADMIN_PASSWORD_HASH = (
    'pbkdf2_sha256$1200000$lhgqh9mswpTOscm3RNJ1ZF$'
    'IxSYAI0AtNluN0AsTe3AgIxkbO0y9Cto8f9/a9o3rOk='
)

ADMIN_EMAILS = (
    'ieltsberuniy@gmail.com',
    'rabbit.noir2009@gmail.com',
)


def _username_for(User, email):
    base = email.split('@')[0].lower().replace('.', '').replace('-', '').replace('_', '')
    username = base
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f'{base}{counter}'
        counter += 1
    return username


def ensure_teacher_accounts(apps, schema_editor):
    """Rasmiy admin Gmail hisoblarini yaratadi/ustoz qiladi va parol o'rnatadi."""
    User = apps.get_model('api', 'User')

    for email in ADMIN_EMAILS:
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User(
                username=_username_for(User, email),
                email=email,
                first_name='IELTS',
                last_name='Beruniy',
            )
        user.role = 'teacher'
        user.password = ADMIN_PASSWORD_HASH
        user.is_active = True
        user.save()
        print(f'ensure_teacher_accounts: {email} -> teacher')


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0031_purge_non_gmail_test_users'),
    ]

    operations = [
        migrations.RunPython(ensure_teacher_accounts, migrations.RunPython.noop),
    ]
