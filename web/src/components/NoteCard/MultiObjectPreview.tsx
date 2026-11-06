import AuthImage from '../AuthImage/AuthImage'
import type { NoteObject } from '../../types'
import { getObjectPreviewSource } from '../../utils/notePreview'
import { LinkFavicon, MediaPlaceholder } from './CardParts'
import { VideoPreviewFrame } from './VideoPreviewFrame'
import { documentThumb, intrinsicRatioStyle } from './cardModel'
import styles from './NoteCard.module.css'

/** Content of one mosaic cell / slot. */
function LayerContent({ obj, fallback }: { obj: NoteObject | undefined; fallback: string }) {
  if (obj?.type === 'image') {
    return <AuthImage src={getObjectPreviewSource(obj)} alt="" className={styles.collectionLayerImg} />
  }
  if (obj?.type === 'video') {
    return obj.thumbnailUrl
      ? <VideoPreviewFrame src={obj.thumbnailUrl} className={styles.collectionLayerImg} object={obj} />
      : <MediaPlaceholder type="video" className={styles.collectionLayerBg} />
  }
  if (obj?.type === 'audio') {
    return <MediaPlaceholder type="audio" className={styles.collectionLayerBg} />
  }
  if (obj?.type === 'document') {
    const thumb = documentThumb(obj)
    return thumb
      ? <AuthImage src={thumb} alt="" className={styles.collectionLayerImg} style={intrinsicRatioStyle(obj)} />
      : <MediaPlaceholder type="document" className={styles.collectionLayerBg} label={obj.filename ?? null} />
  }
  if (obj?.type === 'link') {
    if (obj.thumbnailUrl) return <AuthImage src={obj.thumbnailUrl} alt="" className={styles.collectionLayerImg} />
    return (
      <div className={`${styles.collectionLayerBg} ${styles.collectionLayerLink}`} style={{ background: fallback }}>
        <div className={styles.linkCoverInner}>
          <LinkFavicon url={obj.content} />
        </div>
      </div>
    )
  }
  return <div className={styles.collectionLayerBg} style={{ background: fallback }} />
}

/** A full-bleed tile (image/video/link thumbnail) or a slot wrapping a placeholder layer. */
function VisualTile({
  obj,
  fallback,
  imageClassName,
  slotClassName,
}: {
  obj: NoteObject
  fallback: string
  imageClassName: string
  slotClassName: string
}) {
  if (obj.type === 'image') {
    return <AuthImage src={getObjectPreviewSource(obj)} alt="" className={imageClassName} />
  }
  if (obj.type === 'video' && obj.thumbnailUrl) {
    return <VideoPreviewFrame src={obj.thumbnailUrl} className={imageClassName} object={obj} />
  }
  if (obj.type === 'link' && obj.thumbnailUrl) {
    return <AuthImage src={obj.thumbnailUrl} alt="" className={imageClassName} />
  }
  return (
    <div className={slotClassName}>
      <LayerContent obj={obj} fallback={fallback} />
    </div>
  )
}

/** Cover for notes with several visual objects: single, pair or mosaic layout. */
export function MultiObjectPreview({ visualObjs, fallback }: { visualObjs: NoteObject[]; fallback: string }) {
  if (visualObjs.length === 0) {
    return (
      <div className={styles.collectionSingleNonImage}>
        <LayerContent obj={undefined} fallback={fallback} />
      </div>
    )
  }

  if (visualObjs.length === 1) {
    return (
      <VisualTile
        obj={visualObjs[0]}
        fallback={fallback}
        imageClassName={styles.collectionSingle}
        slotClassName={styles.collectionSingleNonImage}
      />
    )
  }

  if (visualObjs.length === 2) {
    return (
      <div className={styles.collectionPair}>
        {visualObjs.map(obj => (
          <VisualTile
            key={obj.id}
            obj={obj}
            fallback={fallback}
            imageClassName={styles.collectionPairImg}
            slotClassName={styles.collectionPairSlot}
          />
        ))}
      </div>
    )
  }

  const visible = visualObjs.slice(0, 4)
  return (
    <div className={styles.collectionMosaic}>
      {visible.map((obj, index) => (
        <div key={obj.id} className={index === 0 ? styles.collectionMosaicMain : styles.collectionMosaicCell}>
          <LayerContent obj={obj} fallback={fallback} />
        </div>
      ))}
      {visualObjs.length > visible.length && (
        <span className={styles.collectionMoreBadge}>+{visualObjs.length - visible.length}</span>
      )}
    </div>
  )
}
