import QRCode from 'qrcode'
import { useEffect, useState } from 'react'

export function SpectatorQR({ url, viewers }: { url: string | null; viewers: number }) {
  const [img, setImg] = useState<string | null>(null)

  useEffect(() => {
    if (!url) {
      setImg(null)
      return
    }
    let dead = false
    void QRCode.toDataURL(url, { margin: 1, width: 168, color: { dark: '#e8f0ec', light: '#00000000' } })
      .then((data) => {
        if (!dead) setImg(data)
      })
      .catch((err: unknown) => {
        console.error('flick: QR generation failed', err)
        if (!dead) setImg(null)
      })
    return () => {
      dead = true
    }
  }, [url])

  return (
    <section className="flex min-w-0 flex-col gap-3 rounded-[10px] border border-line bg-panel px-4 py-3.5">
      <span className="font-mono text-[10.5px] uppercase tracking-widest text-muted">Spectator</span>
      {!url && <p className="text-sm text-muted">No spectator link. The relay is not connected.</p>}
      {url && img && (
        <img src={img} alt="QR code for the spectator view" className="h-40 w-40" style={{ imageRendering: 'pixelated' }} />
      )}
      {url && (
        <a href={url} className="break-all text-sm text-accent">
          {url}
        </a>
      )}
      <span className="font-mono text-[11px] text-muted">{viewers} viewers</span>
    </section>
  )
}
