from app.env import load_env
from app.service import run_daily

load_env()


def main():
    result = run_daily()
    print(
        f"{result['date']}: {result['dishes']} dishes, "
        f"{result['stored']} emails saved, {result['sent']} sent"
    )


if __name__ == "__main__":
    main()
