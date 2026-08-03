from django import template

register = template.Library()


@register.filter
def get_item(value, key):
    """Lug'at/o'byektdan o'zgaruvchan kalit bilan qiymat oladi (xavfsiz)."""
    if value is None:
        return None
    if hasattr(value, key):
        return getattr(value, key)
    if isinstance(value, dict):
        return value.get(key)
    try:
        return value[key]
    except (KeyError, TypeError, IndexError):
        return None
