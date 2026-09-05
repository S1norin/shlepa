#!/usr/bin/env bash
set -euo pipefail
cat > /app/security_report.json <<'JSON'
{
  "findings": [
    {
      "title": "Authenticated users can delete another account's invoice",
      "severity": "high",
      "category": "CWE-862: Missing Authorization",
      "location": "src/server.js, deleteInvoice, DELETE /invoices/:invoiceId",
      "evidence": "The handler verifies only that req.session.user exists. It loads an arbitrary invoiceId and deletes it without comparing invoice.owner to the authenticated user or evaluating an administrative role.",
      "impact": "Any logged-in user who knows or guesses another user's invoice ID can delete that cross-account billing record.",
      "recommendation": "Enforce an access-control policy after loading the invoice and before deletion: require invoice ownership or an explicit billing-admin role, otherwise return 403."
    }
  ]
}
JSON
