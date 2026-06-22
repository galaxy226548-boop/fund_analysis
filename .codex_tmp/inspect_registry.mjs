import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const path = "A_data/data/data_registry.xlsx";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
const sheet = workbook.worksheets.getItemAt(0);
const used = sheet.getUsedRange(true);
console.log("name=" + sheet.name);
console.log("address=" + used.address);
console.log("sample=" + JSON.stringify(sheet.getRange("A1:C6").values));
