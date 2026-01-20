"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

type OCRBox = {
  id: string;
  text: string;
  box: { x: number; y: number; w: number; h: number };
};

type OCRResult = {
  width: number;
  height: number;
  text: string;
  boxes: OCRBox[];
};

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [ocr, setOcr] = useState<OCRResult | null>(null);
  const [boxes, setBoxes] = useState<OCRBox[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scale, setScale] = useState(1);

  const imgRef = useRef<HTMLImageElement>(null);

  const ocrText = useMemo(() => boxes.map((box) => box.text).join("\n"), [boxes]);

  const updateScale = useCallback(() => {
    const img = imgRef.current;
    if (!img || !img.naturalWidth) return;
    const newScale = img.clientWidth / img.naturalWidth;
    if (Number.isFinite(newScale) && newScale > 0) {
      setScale(newScale);
    }
  }, []);

  useEffect(() => {
    updateScale();
  }, [imageUrl, updateScale]);

  useEffect(() => {
    window.addEventListener("resize", updateScale);
    return () => window.removeEventListener("resize", updateScale);
  }, [updateScale]);

  useEffect(() => {
    return () => {
      if (imageUrl) URL.revokeObjectURL(imageUrl);
    };
  }, [imageUrl]);

  async function onRunOcr() {
    if (!file) return;
    setError(null);
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`${BACKEND_URL}/api/ocr`, { method: "POST", body: fd });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`${res.status} ${res.statusText} ${text}`);
      }
      const data = (await res.json()) as OCRResult;
      setOcr(data);
      setBoxes(data.boxes ?? []);
    } catch (err: any) {
      setError(err?.message ?? String(err));
      setOcr(null);
      setBoxes([]);
    } finally {
      setBusy(false);
    }
  }

  function onFileChange(e: ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0] ?? null;
    setFile(selected);
    setOcr(null);
    setBoxes([]);
    setError(null);
    if (imageUrl) URL.revokeObjectURL(imageUrl);
    setImageUrl(selected ? URL.createObjectURL(selected) : null);
  }

  function updateBoxText(id: string, text: string) {
    setBoxes((prev) => prev.map((box) => (box.id === id ? { ...box, text } : box)));
  }

  function drawWrappedText(
    ctx: CanvasRenderingContext2D,
    text: string,
    x: number,
    y: number,
    maxWidth: number,
    lineHeight: number,
  ) {
    const words = text.split(/\s+/).filter(Boolean);
    if (words.length === 0) return;
    let line = "";
    let yOffset = y;
    for (const word of words) {
      const testLine = line ? `${line} ${word}` : word;
      const metrics = ctx.measureText(testLine);
      if (metrics.width > maxWidth && line) {
        ctx.fillText(line, x, yOffset);
        line = word;
        yOffset += lineHeight;
      } else {
        line = testLine;
      }
    }
    if (line) ctx.fillText(line, x, yOffset);
  }

  async function onDownload() {
    if (!imageUrl) return;
    const img = imgRef.current;
    if (!img || !img.naturalWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    ctx.textBaseline = "top";
    for (const box of boxes) {
      const { x, y, w, h } = box.box;
      const fontSize = Math.max(12, Math.round(h * 0.8));
      ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
      ctx.fillRect(x, y, w, h);
      ctx.fillStyle = "#111";
      ctx.font = `${fontSize}px sans-serif`;
      drawWrappedText(ctx, box.text, x, y, w, Math.round(fontSize * 1.2));
    }
    const link = document.createElement("a");
    link.href = canvas.toDataURL("image/png");
    link.download = "edited.png";
    link.click();
  }

  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: "0 auto" }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 6 }}>
        OCR 图片编辑（上传 → OCR → 直接在图上改字）
      </h1>
      <p style={{ opacity: 0.7, marginBottom: 18 }}>
        支持 JPG/PNG，OCR 结果会显示在右侧文本框，同时可直接在图上编辑并下载。
      </p>

      <div style={{ display: "flex", gap: 16, alignItems: "center", marginBottom: 12 }}>
        <input type="file" accept="image/png,image/jpeg" onChange={onFileChange} />
        <button
          onClick={onRunOcr}
          disabled={!file || busy}
          style={{ padding: "8px 14px", fontWeight: 600 }}
        >
          {busy ? "OCR 中..." : "开始 OCR"}
        </button>
        <button
          onClick={onDownload}
          disabled={!imageUrl || boxes.length === 0}
          style={{ padding: "8px 14px", fontWeight: 600 }}
        >
          下载编辑后图片
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: 16 }}>
        <div
          style={{
            border: "1px solid rgba(0,0,0,0.12)",
            padding: 12,
            borderRadius: 8,
            minHeight: 360,
          }}
        >
          {imageUrl ? (
            <div style={{ position: "relative", width: "100%" }}>
              <img
                ref={imgRef}
                src={imageUrl}
                alt="uploaded"
                style={{ maxWidth: "100%", height: "auto", display: "block" }}
                onLoad={updateScale}
              />
              {boxes.map((box) => (
                <textarea
                  key={box.id}
                  value={box.text}
                  onChange={(e) => updateBoxText(box.id, e.target.value)}
                  style={{
                    position: "absolute",
                    left: box.box.x * scale,
                    top: box.box.y * scale,
                    width: Math.max(40, box.box.w * scale),
                    height: Math.max(24, box.box.h * scale),
                    border: "1px solid rgba(0,0,0,0.25)",
                    background: "rgba(255,255,255,0.7)",
                    fontSize: Math.max(10, box.box.h * scale * 0.7),
                    padding: "2px 4px",
                    resize: "none",
                    overflow: "hidden",
                  }}
                />
              ))}
            </div>
          ) : (
            <div style={{ opacity: 0.6 }}>请选择图片后预览。</div>
          )}
        </div>

        <div
          style={{
            border: "1px solid rgba(0,0,0,0.12)",
            padding: 12,
            borderRadius: 8,
            minHeight: 360,
            display: "grid",
            gap: 8,
          }}
        >
          <div style={{ fontWeight: 600 }}>OCR 结果</div>
          <textarea
            readOnly
            value={ocrText}
            placeholder="OCR 识别结果会显示在这里"
            rows={16}
            style={{ width: "100%", padding: 10, resize: "vertical" }}
          />
          {ocr ? (
            <div style={{ fontSize: 12, opacity: 0.7 }}>
              原图尺寸：{ocr.width} × {ocr.height}，识别到 {boxes.length} 行文本
            </div>
          ) : null}
        </div>
      </div>

      {error ? (
        <pre
          style={{
            marginTop: 16,
            padding: 12,
            background: "rgba(255,0,0,0.06)",
            border: "1px solid rgba(255,0,0,0.25)",
            whiteSpace: "pre-wrap",
          }}
        >
          {error}
        </pre>
      ) : null}
    </div>
  );
}
