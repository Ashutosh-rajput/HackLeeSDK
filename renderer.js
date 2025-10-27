const screenshotImage = document.getElementById('screenshot');
const captionText = document.getElementById('caption');

window.electronAPI.onScreenshotAndCaption(({ image, caption }) => {
  screenshotImage.src = image;
  captionText.innerText = caption;
});