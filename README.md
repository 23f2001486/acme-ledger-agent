# Acme Appliances Order Ledger Agent

## What it does
A small FastAPI service with a public `POST /ask` endpoint that accepts:
```json
{"question":"What was the total revenue in USD from the North region in March 2026?"}
```
and returns:
```json
{"answer":1234.56}
```

It loads `orders.ndjson`, keeps the newest `updated_at` row for each order ID, converts currencies using the supplied API rates, uses Asia/Kolkata business dates, and counts only `paid` orders as revenue.

## Run locally (Windows PowerShell)
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --reload
```
Open `http://127.0.0.1:8000` to check the service. Open `http://127.0.0.1:8000/docs` to try `POST /ask`.

Example request:
```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask -ContentType "application/json" -Body '{"question":"What was the total revenue in USD from the North region in March 2026?"}'
```

## Deploy on Render
1. Unzip the project and create a GitHub repository.
2. Upload `app.py`, `orders.ndjson`, `requirements.txt`, and `render.yaml` to the repository root.
3. On Render, choose **New +** → **Blueprint** and connect that GitHub repository.
4. Render reads `render.yaml`; deploy the web service.
5. When it finishes, copy the HTTPS URL, e.g. `https://your-service-name.onrender.com`.
6. Test it:
```powershell
Invoke-RestMethod -Method Post -Uri https://YOUR-SERVICE.onrender.com/ask -ContentType "application/json" -Body '{"question":"What was the total revenue in USD from the North region in March 2026?"}'
```
7. Submit the base URL plus `/ask` as the endpoint, if the assignment asks for the endpoint URL.

## Important
- This is a deterministic rule-based parser, not a full language model. It handles common question forms about revenue, refunds, order counts, units, and top products/customers. Before submission, test it against the assignment's exact sample/paraphrased questions.
- Refunds are calculated from current rows with status `refunded`; the source notes explicitly define paid revenue, but do not separately specify a refund accounting formula.
