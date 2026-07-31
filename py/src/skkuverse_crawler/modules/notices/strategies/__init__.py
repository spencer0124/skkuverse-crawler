from .skku_standard import SkkuStandardStrategy
from .wordpress_api import WordPressApiStrategy
from .skkumed_asp import SkkumedAspStrategy
from .jsp_dorm import JspDormStrategy
from .custom_php import CustomPhpStrategy
from .gnuboard import GnuboardStrategy
from .gnuboard_custom import GnuboardCustomStrategy
from .pyxis_api import PyxisApiStrategy
from .webflow_skku import WebflowSkkuStrategy

STRATEGY_MAP: dict[str, type] = {
    "skku-standard": SkkuStandardStrategy,
    "wordpress-api": WordPressApiStrategy,
    "skkumed-asp": SkkumedAspStrategy,
    "jsp-dorm": JspDormStrategy,
    "custom-php": CustomPhpStrategy,
    "gnuboard": GnuboardStrategy,
    "gnuboard-custom": GnuboardCustomStrategy,
    "pyxis-api": PyxisApiStrategy,
    "webflow-skku": WebflowSkkuStrategy,
}
