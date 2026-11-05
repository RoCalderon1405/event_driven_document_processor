from fastapi import FastAPI

from event_driven_document_processor.bootstrap.routes import api_router

app = FastAPI(title="EventDriven Document Processor", version="0.1.0")
app.include_router(api_router)


@app.get("/health", tags=["Health"])
def health() -> dict[str, str]:
    return {"status": "healthy", "service": "document-processor"}
