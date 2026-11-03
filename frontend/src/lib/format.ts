// 7Xy...3kP style. Pass a larger `chars` if you want more of the address.
export function truncateAddress(address: string, chars = 3) {
  if (address.length <= chars * 2 + 3) return address
  return `${address.slice(0, chars)}...${address.slice(-chars)}`
}
