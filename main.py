from dotenv import load_dotenv

load_dotenv()

from AgenticWorkflow.graph import app

if __name__ == "__main__":
    result = app.invoke(input={"question": "Who is incharge of RBI in 2026"})
    for key, value in result.items():
        print(f"key:= {key}\nValue:= {value}\n")
