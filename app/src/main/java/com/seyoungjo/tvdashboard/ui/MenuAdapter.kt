package com.seyoungjo.tvdashboard.ui

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Handler
import android.os.Looper
import android.util.LruCache
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.seyoungjo.tvdashboard.R
import com.seyoungjo.tvdashboard.data.MenuEntry
import java.io.File
import java.util.concurrent.Executors

/** 왼쪽 사이드바: 정사각형 아이콘(폴더의 icon.png) + 이름 */
class MenuAdapter(
    private val onClick: (MenuEntry) -> Unit,
) : RecyclerView.Adapter<MenuAdapter.Holder>() {

    var items: List<MenuEntry> = emptyList()
        private set
    var selectedFolder: String? = null
        set(v) {
            val old = field
            field = v
            items.indexOfFirst { it.folder == old }.takeIf { it >= 0 }?.let { notifyItemChanged(it) }
            items.indexOfFirst { it.folder == v }.takeIf { it >= 0 }?.let { notifyItemChanged(it) }
        }

    private val cache = object : LruCache<String, Bitmap>(24 * 1024 * 1024) {
        override fun sizeOf(key: String, value: Bitmap) = value.byteCount
    }
    private val io = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())

    fun submit(list: List<MenuEntry>) {
        items = list
        notifyDataSetChanged()
    }

    class Holder(v: View) : RecyclerView.ViewHolder(v) {
        val frame: View = v.findViewById(R.id.tileFrame)
        val image: ImageView = v.findViewById(R.id.tileImage)
        val initial: TextView = v.findViewById(R.id.tileInitial)
        val name: TextView = v.findViewById(R.id.tileName)
        var key: String? = null
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder {
        val v = LayoutInflater.from(parent.context).inflate(R.layout.item_menu_tile, parent, false)
        val h = Holder(v)
        h.frame.clipToOutline = true
        return h
    }

    override fun getItemCount() = items.size

    override fun onBindViewHolder(h: Holder, position: Int) {
        val e = items[position]
        h.name.text = e.title
        h.itemView.isSelected = e.folder == selectedFolder
        h.itemView.contentDescription = e.title
        h.itemView.setOnClickListener { onClick(e) }
        h.initial.text = e.title.take(1)
        val img = e.image
        if (img == null) {
            h.key = null
            h.image.setImageDrawable(null)
            h.initial.visibility = View.VISIBLE
            return
        }
        val key = "${img.path}:${img.lastModified()}:${img.length()}"
        h.key = key
        val cached = cache.get(key)
        if (cached != null) {
            h.image.setImageBitmap(cached); h.initial.visibility = View.GONE
            return
        }
        h.image.setImageDrawable(null)
        h.initial.visibility = View.VISIBLE
        io.execute {
            val bmp = decode(img, 256)
            main.post {
                if (bmp != null) cache.put(key, bmp)
                if (h.key == key && bmp != null) {
                    h.image.setImageBitmap(bmp); h.initial.visibility = View.GONE
                }
            }
        }
    }

    private fun decode(f: File, target: Int): Bitmap? = try {
        val o = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(f.path, o)
        var sample = 1
        while (o.outWidth / (sample * 2) >= target && o.outHeight / (sample * 2) >= target) sample *= 2
        BitmapFactory.decodeFile(f.path, BitmapFactory.Options().apply { inSampleSize = sample })
    } catch (e: Throwable) { null }
}
