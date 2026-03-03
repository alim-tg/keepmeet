import { useCallback, useState } from "react"
import { cn } from "@/lib/utils"
import { Upload, Music } from "lucide-react"

interface FileDropzoneProps {
  onFile: (file: File) => void
  file: File | null
}

const ACCEPT = ".m4a,.wav,.mp3"

export function FileDropzone({ onFile, file }: FileDropzoneProps) {
  const [dragging, setDragging] = useState(false)

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragging(false)
      const f = e.dataTransfer.files[0]
      if (f) onFile(f)
    },
    [onFile]
  )

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0]
      if (f) onFile(f)
    },
    [onFile]
  )

  return (
    <label
      className={cn(
        "group relative flex flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed p-10 cursor-pointer transition-all duration-300 overflow-hidden",
        dragging
          ? "border-primary/60 bg-primary/[0.08] shadow-lg shadow-primary/10"
          : "border-white/10 hover:border-primary/30 hover:bg-white/[0.02]",
        file && "border-primary/30 bg-primary/[0.04]"
      )}
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
    >
      <div className={cn(
        "flex h-14 w-14 items-center justify-center rounded-2xl transition-all duration-300",
        file
          ? "bg-primary/15 text-primary"
          : "bg-white/[0.04] text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary"
      )}>
        {file ? <Music className="h-6 w-6" /> : <Upload className="h-6 w-6" />}
      </div>
      {file ? (
        <div className="text-center">
          <span className="text-sm font-medium text-foreground">{file.name}</span>
          <p className="text-xs text-muted-foreground mt-1">{(file.size / 1024 / 1024).toFixed(1)} MB</p>
        </div>
      ) : (
        <div className="text-center">
          <span className="text-sm font-medium text-foreground/80">
            Drop audio file here
          </span>
          <p className="text-xs text-muted-foreground mt-1">
            Supports m4a, wav, mp3
          </p>
        </div>
      )}
      <input type="file" accept={ACCEPT} className="hidden" onChange={handleChange} />
    </label>
  )
}
