// Framework-neutral sketch of the synthetic billing routes.
const invoices = new Map([
  ['inv-100', { owner: 'alice', status: 'draft' }],
  ['inv-200', { owner: 'bob', status: 'draft' }],
]);

function deleteInvoice(req, res) {
  if (!req.session || !req.session.user) {
    return res.status(401).json({ error: 'login required' });
  }
  const invoice = invoices.get(req.params.invoiceId);
  if (!invoice) return res.status(404).json({ error: 'not found' });
  invoices.delete(req.params.invoiceId);
  return res.status(204).end();
}

module.exports = { deleteInvoice, invoices };
