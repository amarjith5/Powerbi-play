from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import uvicorn

load_dotenv()

from models import ChatRequest, ChatResponse, ReportMeta
from powerbi_client import PowerBIClient
from chat_engine import generate_response

app = FastAPI(title="BISync API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pbi = PowerBIClient()


@app.get("/")
def root():
    return {"status": "BISync API running", "version": "1.0.0"}


@app.get("/reports", response_model=list[ReportMeta])
def get_reports():
    """List all available Power BI reports"""
    return pbi.get_reports()


@app.get("/reports/{report_id}/data")
def get_report_data(report_id: str):
    """Fetch dataset for a specific report"""
    try:
        dataset = pbi.get_dataset(report_id)
        return dataset
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Report not found: {str(e)}")


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Main chat endpoint — handles all Q&A over Power BI data"""
    dataset_metrics = None
    if request.report_context:
        # Extract report_id from context string like "rpt-001"
        for report in pbi.get_reports():
            if report.id in (request.report_context or ""):
                dataset = pbi.get_dataset(report.id)
                dataset_metrics = dataset.metrics
                break

    response = await generate_response(request, dataset_metrics)
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         