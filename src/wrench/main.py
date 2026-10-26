from dotenv import load_dotenv
load_dotenv()

from wrench.slack.bot import start


def main():
    print("Wrench is running")
    start()


if __name__ == "__main__":
    main()
