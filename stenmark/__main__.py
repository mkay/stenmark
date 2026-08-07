import locale
import sys

from stenmark import LOCALEDIR
from stenmark.i18n import GETTEXT_DOMAIN
from stenmark.app import Application


def main():
    # Honour the user's locale, and point the C library at our catalogues so
    # anything translated below the Python layer resolves too.
    try:
        locale.setlocale(locale.LC_ALL, "")
        locale.bindtextdomain(GETTEXT_DOMAIN, LOCALEDIR)
        locale.textdomain(GETTEXT_DOMAIN)
    except (locale.Error, AttributeError):
        # An unsupported LANG shouldn't stop the app from starting.
        pass

    app = Application()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
