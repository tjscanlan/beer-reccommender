import uvicorn


def main():
    # host=0.0.0.0 so your iPhone can reach the app over your local network
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
