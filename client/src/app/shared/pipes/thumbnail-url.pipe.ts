import { Pipe, PipeTransform } from '@angular/core';

/** Above 640 the server renders the original. `v` skips the soft frame browsers
 *  cached under the old URL; `ngsw-bypass` because the service worker ignores
 *  Cache-Control. */
export function thumbnailUrl(path: string, size?: number): string {
  const params = new URLSearchParams({ path });
  if (size) params.set('size', String(size));
  if (size && size > 640) {
    params.set('v', '2');
    params.set('ngsw-bypass', '1');
  }
  return `/thumbnail?${params}`;
}

@Pipe({ name: 'thumbnailUrl', standalone: true, pure: true })
export class ThumbnailUrlPipe implements PipeTransform {
  transform(path: string, size?: number): string {
    return thumbnailUrl(path, size);
  }
}

@Pipe({ name: 'imageUrl', standalone: true, pure: true })
export class ImageUrlPipe implements PipeTransform {
  transform(path: string, fallbackThumbnail = false): string {
    const params = new URLSearchParams({ path });
    if (fallbackThumbnail) params.set('fallback', 'thumbnail');
    return `/image?${params}`;
  }
}

@Pipe({ name: 'faceThumbnailUrl', standalone: true, pure: true })
export class FaceThumbnailUrlPipe implements PipeTransform {
  transform(faceId: number): string {
    return `/face_thumbnail/${faceId}`;
  }
}

@Pipe({ name: 'personThumbnailUrl', standalone: true, pure: true })
export class PersonThumbnailUrlPipe implements PipeTransform {
  transform(personId: number): string {
    return `/person_thumbnail/${personId}`;
  }
}
