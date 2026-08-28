self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { title: "ERP notification", body: "You have a new ERP update." };
  }

  event.waitUntil(self.registration.showNotification(payload.title || "ERP notification", {
    body: payload.body || "You have a new ERP update.",
    tag: payload.data?.event_type || "erp-notification",
    data: payload.data || {},
    renotify: true,
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = event.notification.data?.url || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ("focus" in client) {
          client.navigate(target);
          return client.focus();
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});
