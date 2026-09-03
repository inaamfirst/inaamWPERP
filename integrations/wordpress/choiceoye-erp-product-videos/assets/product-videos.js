(() => {
  const dialog = document.querySelector("[data-choiceoye-dialog]");
  if (!dialog) return;

  const player = dialog.querySelector("[data-choiceoye-player]");
  const closeButton = dialog.querySelector(".choiceoye-video-close");
  let opener = null;

  const close = () => {
    if (dialog.hidden) return;
    player.replaceChildren();
    dialog.hidden = true;
    document.body.classList.remove("choiceoye-video-open");
    if (opener) opener.focus();
    opener = null;
  };

  const open = (button) => {
    const source = button.dataset.source;
    const url = button.dataset.playerUrl;
    if (!url) return;
    opener = button;
    let media;
    if (source === "mp4" || source === "uploaded") {
      media = document.createElement("video");
      media.controls = true;
      media.playsInline = true;
      media.preload = "metadata";
      media.src = url;
    } else {
      media = document.createElement("iframe");
      media.src = url;
      media.title = button.getAttribute("aria-label") || "Product video";
      media.allow = "fullscreen; picture-in-picture";
      media.allowFullscreen = true;
      media.referrerPolicy = "strict-origin-when-cross-origin";
    }
    player.replaceChildren(media);
    dialog.hidden = false;
    document.body.classList.add("choiceoye-video-open");
    closeButton.focus();
  };

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-choiceoye-video]");
    if (trigger) {
      event.preventDefault();
      open(trigger);
      return;
    }
    if (event.target.closest("[data-choiceoye-close]")) close();
  });

  document.addEventListener("keydown", (event) => {
    if (dialog.hidden) return;
    if (event.key === "Escape") close();
    if (event.key === "Tab") {
      event.preventDefault();
      closeButton.focus();
    }
  });
})();
