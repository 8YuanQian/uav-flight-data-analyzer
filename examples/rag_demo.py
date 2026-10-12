from src.rag import UAVAssistant


def main():
    assistant = UAVAssistant()
    question = input("question: ")
    answer = assistant.ask(question)
    print(f"Answer: {answer}")


if __name__ == "__main__":
    main()
