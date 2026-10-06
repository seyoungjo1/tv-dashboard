package com.seyoungjo.tvdashboard.server

import java.net.Inet4Address
import java.net.Inet6Address
import java.net.InetAddress
import java.net.NetworkInterface

object NetInfo {
    data class Addr(val ip: String, val tailscale: Boolean, val iface: String)

    /** 100.64.0.0/10 (Tailscale IPv4) 또는 fd7a:115c:a1e0::/48 (Tailscale IPv6) */
    fun isTailscale(ip: String): Boolean {
        val clean = ip.substringBefore('%').removePrefix("/")
        return try {
            val a = InetAddress.getByName(clean)
            when (a) {
                is Inet4Address -> {
                    val b = a.address
                    (b[0].toInt() and 0xff) == 100 && (b[1].toInt() and 0xc0) == 64
                }
                is Inet6Address -> {
                    val b = a.address
                    val v4 = isV4Mapped(b)
                    if (v4 != null) isTailscale(v4)
                    else (b[0].toInt() and 0xff) == 0xfd && (b[1].toInt() and 0xff) == 0x7a &&
                        (b[2].toInt() and 0xff) == 0x11 && (b[3].toInt() and 0xff) == 0x5c &&
                        (b[4].toInt() and 0xff) == 0xa1 && (b[5].toInt() and 0xff) == 0xe0
                }
                else -> false
            }
        } catch (e: Exception) { false }
    }

    private fun isV4Mapped(b: ByteArray): String? {
        if (b.size != 16) return null
        for (i in 0 until 10) if (b[i].toInt() != 0) return null
        if ((b[10].toInt() and 0xff) != 0xff || (b[11].toInt() and 0xff) != 0xff) return null
        return "${b[12].toInt() and 0xff}.${b[13].toInt() and 0xff}.${b[14].toInt() and 0xff}.${b[15].toInt() and 0xff}"
    }

    fun isLoopback(ip: String): Boolean = try {
        InetAddress.getByName(ip.substringBefore('%')).isLoopbackAddress
    } catch (e: Exception) { false }

    /** TV 의 IPv4 주소 목록 (Tailscale 주소 포함) */
    fun addresses(): List<Addr> = try {
        NetworkInterface.getNetworkInterfaces().toList()
            .filter { it.isUp && !it.isLoopback }
            .flatMap { ni ->
                ni.inetAddresses.toList().filterIsInstance<Inet4Address>()
                    .map { Addr(it.hostAddress ?: "", isTailscale(it.hostAddress ?: ""), ni.name) }
            }
            .filter { it.ip.isNotEmpty() }
            .sortedBy { if (it.tailscale) 1 else 0 }
    } catch (e: Exception) { emptyList() }
}
