/** The example from the brief, plus a few rows that are fun to try patterns on. */
const ROWS = [
  ["ID", "Name", "Email", "Phone", "Joined", "Notes"],
  ["1", "John Doe", "john.doe@example.com", "(415) 555-0132", "2023-01-15", "Prefers email; backup john@doe.dev"],
  ["2", "Jane Smith", "jane_smith@domain.com", "415.555.0199", "15/02/2023", "Called on 2023-02-20, see https://crm.example.com/t/88"],
  ["3", "Alice Brown", "alice.brown@website.org", "+1 212 555 0147", "March 3, 2023", "VIP. Card ending 4242 4242 4242 4242"],
  ["4", "Bob Martinez", "bob.martinez@company.co", "212-555-0110", "2023/04/09", "Asked to update address"],
  ["5", "Chen Wei", "chen.wei@example.cn", "(646) 555-0175", "09-05-2023", "Follow up at http://example.org/help"],
];

const toCsvCell = (value) => (/[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value);

export function sampleFile() {
  const csv = ROWS.map((row) => row.map(toCsvCell).join(",")).join("\n");
  return new File([csv], "sample_contacts.csv", { type: "text/csv" });
}
