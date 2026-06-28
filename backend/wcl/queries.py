"""GraphQL query templates for WCL v2 API."""

REPORT_FIGHTS = """
query ReportFights($code: String!, $killType: KillType) {
  reportData {
    report(code: $code) {
      title
      owner {
        name
      }
      startTime
      endTime
      fights(killType: $killType) {
        id
        name
        encounterID
        kill
        startTime
        endTime
        difficulty
        fightPercentage
      }
      masterData {
        actors {
          id
          name
          type
          subType
          server
        }
        abilities {
          gameID
          name
          type
        }
      }
    }
  }
}
"""

REPORT_EVENTS = """
query ReportEvents($code: String!, $fightIDs: [Int]!, $dataType: EventDataType!, $startTime: Float!, $endTime: Float!, $filterExpression: String, $sourceID: Int, $targetID: Int) {
  reportData {
    report(code: $code) {
      events(
        fightIDs: $fightIDs
        dataType: $dataType
        startTime: $startTime
        endTime: $endTime
        filterExpression: $filterExpression
        sourceID: $sourceID
        targetID: $targetID
      ) {
        data
        nextPageTimestamp
      }
    }
  }
}
"""

REPORT_EVENTS_ENEMY_DEATHS = """
query ReportEnemyDeaths($code: String!, $fightIDs: [Int]!, $startTime: Float!, $endTime: Float!) {
  reportData {
    report(code: $code) {
      events(
        fightIDs: $fightIDs
        dataType: Deaths
        startTime: $startTime
        endTime: $endTime
        hostilityType: Enemies
      ) {
        data
        nextPageTimestamp
      }
    }
  }
}
"""

REPORT_TABLE = """
query ReportTable($code: String!, $fightIDs: [Int]!, $dataType: TableDataType!, $startTime: Float!, $endTime: Float!, $sourceID: Int, $targetID: Int) {
  reportData {
    report(code: $code) {
      table(
        fightIDs: $fightIDs
        dataType: $dataType
        startTime: $startTime
        endTime: $endTime
        sourceID: $sourceID
        targetID: $targetID
      )
    }
  }
}
"""

# v2 dataTypes for events:
# DamageDone, DamageTaken, Healing, Casts, Buffs, Debuffs,
# Deaths, Threat, Resources, Interrupts, Dispels, CombatantInfo

# v2 dataTypes for tables:
# DamageDone, DamageTaken, Healing, Casts, Buffs, Debuffs, Deaths, Threat

# ─── Guild Queries ────────────────────────────────────────────────────

GUILD_ATTENDANCE = """
query GuildAttendance($guildID: Int!, $limit: Int, $page: Int) {
  guildData {
    guild(id: $guildID) {
      id
      name
      server { name slug region { compactName } }
      attendance(limit: $limit, page: $page) {
        data {
          code
          startTime
          zone { name }
          players {
            name
            type
            presence
          }
        }
        has_more_pages
        total
        current_page
        last_page
      }
    }
  }
}
"""
