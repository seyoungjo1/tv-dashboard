package com.seyoungjo.tvdashboard.ui

import android.content.Context
import android.util.AttributeSet
import android.widget.FrameLayout

/** 가로 폭과 같은 높이를 갖는 정사각형 타일 */
class SquareFrameLayout @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null
) : FrameLayout(context, attrs) {
    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        super.onMeasure(widthMeasureSpec, widthMeasureSpec)
    }
}
