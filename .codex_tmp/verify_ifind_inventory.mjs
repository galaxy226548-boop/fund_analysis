import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const path = "/Users/chloezh/Projects/Fund_Analysis/A_data/reference/data_inventory_A.xlsx";
const input = await FileBlob.load(path);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItemAt(0);

const check = await workbook.inspect({
  kind: "table",
  range: `${sheet.name}!A21:F25`,
  include: "values,formulas",
  tableMaxRows: 5,
  tableMaxCols: 6,
});
console.log(check.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "inventory formula error scan",
});
console.log(errors.ndjson);

const preview = await workbook.render({
  sheetName: sheet.name,
  range: "A20:F25",
  format: "png",
  scale: 1.5,
});
await fs.writeFile(
  "/Users/chloezh/Projects/Fund_Analysis/.codex_tmp/inventory_preview.png",
  Buffer.from(await preview.arrayBuffer()),
);
