from django.db import migrations


class Migration(migrations.Migration):
    """News modellari 0015'da SQL bilan allaqachon o'chirilgan (jadvallar yo'q).

    Bu migratsiya faqat Django'ning migratsiya holatini tozalaydi — bazaga
    hech qanday SQL yubormaydi (aks holda mavjud bo'lmagan jadvalni DROP
    qilishga urinib, deployda xato berardi).
    """

    dependencies = [
        ('api', '0024_tool_toolstate_gamerating'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel('NewsRead'),
                migrations.DeleteModel('NewsReaction'),
                migrations.DeleteModel('NewsComment'),
                migrations.DeleteModel('News'),
            ],
            database_operations=[],
        ),
    ]
