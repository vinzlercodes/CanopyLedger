type MoneyLike = {
  readonly amount: string;
  readonly currency: string;
};

const decimal = /^(-?)(\d+)(?:\.(\d+))?$/;

/** Formats an API-issued decimal string without converting it to JavaScript number. */
export function formatMoney(value: MoneyLike): string {
  const match = decimal.exec(value.amount);
  if (match === null) return `${value.currency} ${value.amount}`;

  const [, sign, integer, fraction] = match;
  const groupedInteger = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${value.currency} ${sign}${groupedInteger}${fraction === undefined ? "" : `.${fraction}`}`;
}
