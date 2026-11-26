from dotenv import load_dotenv

load_dotenv()

from AgenticWorkflow.graph import app

if __name__ == "__main__":
    result = app.invoke(input={"question": "What is policies recently introduced by the rbi"})
    for key, value in result.items():
        print(key, value)
