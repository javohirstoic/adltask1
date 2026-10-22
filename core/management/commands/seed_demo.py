from django.core.management.base import BaseCommand

from core import demo


class Command(BaseCommand):
    help = "Namuna tashkilot: 50 xodim, 14 loyiha, 4 guruh va ~6 haftalik xabarlar"

    def add_arguments(self, parser):
        parser.add_argument("--warm", action="store_true", help="keshda yo'q erkin matnlarni AI'ga yuborib keshni to'ldirish (sekin)")

    def handle(self, *args, **options):
        demo.run(warm=options["warm"])
