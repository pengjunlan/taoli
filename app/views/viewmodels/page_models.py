"""View models shared by page controllers and presenters."""

from typing import Dict

from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    href: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "href": self.href,
        }


@dataclass(frozen=True)
class PageConfig:
    key: str
    template_name: str
    title: str
    subtitle: str
    css_name: str = ""
    js_name: str = ""
    show_shell: bool = True
