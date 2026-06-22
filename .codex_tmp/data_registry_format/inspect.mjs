import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const path = "/Users/chloezh/Projects/Fund_Analysis/A_data/data/data_registry.xlsx";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(path));

const sheets = await workbook.inspect({ kind: "sheet", include: "id,name" });
console.log("SHEETS");
console.log(sheets.ndjson);

for (const sheet of workbook.worksheets.items) {
  const used = sheet.getUsedRange();
  console.log(`USED ${sheet.name}: ${used?.address ?? "none"}`);
  if (used && used.rowCount >= 63 && used.columnCount >= 2) {
    const styles = await workbook.inspect({
      kind: "computedStyle",
      sheetId: sheet.name,
      range: "B62:B63",
      maxChars: 6000,
    });
    console.log(`STYLES ${sheet.name}`);
    console.log(styles.ndjson);
    console.log(`VALUES ${sheet.name}`);
    console.log(JSON.stringify(sheet.getRange("B62:B63").values));
  }
}

const preview = await workbook.render({
  sheetName: "Sheet1",
  range: "A58:C73",
  scale: 2,
  format: "png",
});
await fs.writeFile(
  "/Users/chloezh/Projects/Fund_Analysis/.codex_tmp/data_registry_format/preview.png",
  new Uint8Array(await preview.arrayBuffer()),
);
