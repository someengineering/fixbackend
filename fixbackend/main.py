import uvicorn


def main():
    uvicorn.run("fixbackend.app:app", host="0.0.0.0", log_level="info")    

if __name__ == "__main__":
    main()    
