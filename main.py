import json

from dotenv import load_dotenv

load_dotenv()

from AgenticWorkflow.graph import app

if __name__ == "__main__":
    result = app.invoke(
        input={"question": "Write a python program"}
    )
    print(
        json.dumps(
            {"response": result["generation"], "sources": result["sources"]},
            ensure_ascii=False,
            indent=2,
        )
    )
