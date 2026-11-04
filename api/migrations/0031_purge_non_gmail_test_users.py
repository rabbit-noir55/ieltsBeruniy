from django.db import migrations


def purge_non_gmail_test_users(apps, schema_editor):
    """@gmail.com bo'lmagan test o'quvchilarni o'chiradi.

    Ustoz (teacher), is_staff va superuser hisoblar saqlanadi — ular test
    foydalanuvchi hisoblanmaydi. Bog'liq natijalar/davomat/liga yozuvlari
    CASCADE orqali birga o'chadi.
    """
    User = apps.get_model('api', 'User')
    test_users = (
        User.objects.exclude(email__iendswith='@gmail.com')
        .exclude(role='teacher')
        .exclude(is_staff=True)
        .exclude(is_superuser=True)
    )
    emails = list(test_users.values_list('email', flat=True)[:50])
    count = test_users.count()
    test_users.delete()
    print(f"purge_non_gmail_test_users: {count} ta hisob o'chirildi")
    if emails:
        print("  " + ", ".join(str(e) for e in emails))


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0030_alter_examinerlink_unique_together_and_more'),
    ]

    operations = [
        migrations.RunPython(
            purge_non_gmail_test_users,
            migrations.RunPython.noop,
        ),
    ]
