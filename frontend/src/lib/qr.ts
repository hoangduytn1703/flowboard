import QRCode from "qrcode";

/** A QR code as a PNG data URL (drawn here: the payment details never go to a QR web service). */
export function qrDataUrl(text: string, size = 280): Promise<string> {
  return QRCode.toDataURL(text, { margin: 1, width: size, errorCorrectionLevel: "M", color: { dark: "#000000", light: "#ffffff" } });
}
