import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const root = "/Users/chloezh/Projects/Fund_Analysis";
const xlsxPath = `${root}/A_data/reference/data_inventory_A.xlsx`;
const jsonPath = `${root}/A_data/reference/data_inventory_A.json`;

const mappings = [
  {
    fileName: "iFind偏股混合型基金净值变化.xlsx",
    cleanData: "A_data/prepared_data/偏股混合型基金净值筛选长表.parquet",
  },
  {
    fileName: "iFind偏股混合型基金基金规模.xlsx",
    cleanData: "A_data/prepared_data/偏股混合型基金净值筛选长表.parquet",
  },
  {
    fileName: "iFind普通股票型基金净值变化.xlsx",
    cleanData: "A_data/prepared_data/普通股票型基金净值筛选长表.parquet",
  },
  {
    fileName: "iFind普通股票型基金基金规模.xlsx",
    cleanData: "A_data/prepared_data/普通股票型基金净值筛选长表.parquet",
  },
];

function makeRecord(columns, mapping) {
  const values = Object.fromEntries(columns.map((column) => [column, null]));
  values.clean_data = mapping.cleanData;
  values.frequency = "month";
  values.data_source = "iFind_API";
  values.file_name = mapping.fileName;
  values.file_path = `data/iFind_API/${mapping.fileName}`;
  values.sheet_name = "month";
  values.file_type = "xlsx";
  return values;
}

// 更新 JSON：修改已有记录，并补充缺少的规模文件记录。
const inventory = JSON.parse(await fs.readFile(jsonPath, "utf8"));
const jsonSheetName = Object.keys(inventory.sheets)[0];
const jsonSheet = inventory.sheets[jsonSheetName];

for (const mapping of mappings) {
  let record = jsonSheet.records.find(
    (item) => item.file_name === mapping.fileName,
  );
  if (!record) {
    record = makeRecord(jsonSheet.columns, mapping);
    jsonSheet.records.push(record);
  }
  record.clean_data = mapping.cleanData;
}
jsonSheet.row_count = jsonSheet.records.length;
await fs.writeFile(jsonPath, `${JSON.stringify(inventory, null, 2)}\n`, "utf8");

// 更新 Excel：读取现有表格，修改已有行，并在表尾补充规模文件。
const input = await FileBlob.load(xlsxPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItemAt(0);

const rows = sheet.getRange("A1:R30").values
  .filter((row) => row.some((value) => value !== null && value !== ""));
const columns = rows[0];
const cleanDataColumn = columns.indexOf("clean_data");
const fileNameColumn = columns.indexOf("file_name");

for (const mapping of mappings) {
  let rowIndex = rows.findIndex(
    (row, index) => index > 0 && row[fileNameColumn] === mapping.fileName,
  );

  if (rowIndex === -1) {
    const record = makeRecord(columns, mapping);
    const newRow = columns.map((column) => record[column]);
    rows.push(newRow);
    rowIndex = rows.length - 1;
  }
  rows[rowIndex][cleanDataColumn] = mapping.cleanData;
}

const lastRow = rows.length;
sheet.getRange(`A1:R${lastRow}`).values = rows;
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(xlsxPath);

const verification = await workbook.inspect({
  kind: "table",
  range: `${sheet.name}!A1:F${lastRow}`,
  include: "values",
  tableMaxRows: lastRow,
  tableMaxCols: 6,
});
console.log(verification.ndjson);
