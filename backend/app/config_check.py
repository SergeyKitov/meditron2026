"""Run before deploying a changed technical profile or ruleset."""

from app.adapters.reports import load_draft_pair, load_pair
from app.domain.routing import DomainError


def main():
    try:
        profiles, rules = load_draft_pair()
        load_pair()
    except DomainError as exc:
        print(exc.message)
        return 1
    print(f"Конфигурация корректна: {len(profiles)} профиля, {len(rules['rules'])} правил")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
