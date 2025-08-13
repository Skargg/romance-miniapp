import asyncio
import platform
import uvicorn


def main() -> None:
    if platform.system() == "Windows":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass
    uvicorn.run("api.main:app", host="127.0.0.1", port=8080, reload=False)


if __name__ == "__main__":
    main()


