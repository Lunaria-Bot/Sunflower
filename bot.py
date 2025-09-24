if "auto summon" in title:
    print("🔎 Autosummon detected, trying to identify claimer...")

    def resolve_member_by_name(name: str) -> discord.Member | None:
        if not name:
            return None
        name = name.strip()
        # Essai exact sur display_name
        for m in message.guild.members:
            if m.display_name == name:
                return m
        # Essai exact sur username
        for m in message.guild.members:
            if m.name == name:
                return m
        # Essai insensible à la casse
        for m in message.guild.members:
            if m.name.lower() == name.lower():
                return m
        return None

    auto_user = None

    # 1) Cherche une mention
    m = re.search(r"Claimed By\s+<@!?(\d+)>", desc, flags=re.IGNORECASE)
    if m:
        auto_user = message.guild.get_member(int(m.group(1)))

    # 2) Cherche un pseudo texte
    if not auto_user:
        m = re.search(r"Claimed By\s+([^\n<]+)", desc, flags=re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            auto_user = resolve_member_by_name(candidate)

    # 3) Même logique dans les fields
    if not auto_user and embed.fields:
        for field in embed.fields:
            m_txt = re.search(r"Claimed By\s+([^\n<]+)", field.value, flags=re.IGNORECASE)
            if m_txt:
                candidate = m_txt.group(1).strip()
                auto_user = resolve_member_by_name(candidate)
                if auto_user:
                    break

    # 4) Footer
    if not auto_user and embed.footer and embed.footer.text:
        m_txt = re.search(r"Claimed By\s+([^\n<]+)", embed.footer.text, flags=re.IGNORECASE)
        if m_txt:
            candidate = m_txt.group(1).strip()
            auto_user = resolve_member_by_name(candidate)

    # Résultat
    if auto_user:
        paused = await client.redis.get("leaderboard:paused")
        if paused == "true":
            print(f"⏸️ Leaderboard paused, no points added for {auto_user}.")
        else:
            new_score = await client.redis.incr(f"leaderboard:{auto_user.id}")
            print(f"🏆 {auto_user} gained 1 point (autosummon). New score={new_score}")
            log_channel = message.guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(f"🏆 +1 point for {auto_user.mention} (autosummon) — total {new_score}")
    else:
        print("⚠️ Autosummon detected but no claimer found (no match in guild)")
