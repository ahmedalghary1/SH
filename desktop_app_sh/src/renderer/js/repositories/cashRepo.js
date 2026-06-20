import { getMeta, setMeta } from "./syncMetaRepo.js";

const CASH_BALANCE_KEY = "local_cash_balance";

export async function getCashBalance() {
  return Number(await getMeta(CASH_BALANCE_KEY, "0") || 0);
}

export async function adjustCashBalance(amount) {
  const next = await getCashBalance() + Number(amount || 0);
  await setMeta(CASH_BALANCE_KEY, String(next));
  return next;
}
