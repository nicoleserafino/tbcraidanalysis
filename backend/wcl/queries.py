"""GraphQL query templates for WCL v2 API."""

REPORT_FIGHTS = """
query ReportFights($code: String!) {
  reportData {
    report(code: $code) {
      title
      startTime
      endTime
      fights(killType: Encounters) {
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

REPORT_FIGHTS_ALL = """
query ReportFightsAll($code: String!) {
  reportData {
    report(code: $code) {
      title
      owner {
        name
      }
      startTime
      endTime
      fights {
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
# Deaths, Threat, Resources, Interrupts, Dispels

# v2 dataTypes for tables:
# DamageDone, DamageTaken, Healing, Casts, Buffs, Debuffs, Deaths, Threat
