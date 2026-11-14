// What the page works out, kept apart from the page so that it can be tested without a browser.

export function greeting(now) {
  const hour = now.getHours();
  if (hour < 12) return "Good morning.";
  if (hour < 18) return "Good afternoon.";
  return "Good evening.";
}
