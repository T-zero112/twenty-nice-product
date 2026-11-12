package local.tax;
import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;
class RulesSelectionTest {
 private static Rules.Rule rule(String code,String version,List<String> fields,Long min){
  return new Rules.Rule(new Rules.Citation(UUID.randomUUID(),code,version,code,"1"),"c",fields,LocalDate.of(2026,9,1),null,"published",min);
 }
 private static Rules.Rule rule(String code,String version,List<String> fields){ return rule(code,version,fields,null); }
 @Test void guidanceRulesNeverSelectedOrConflict(){
  var s=Rules.selection(List.of(rule("R001","1.0",List.of()),rule("R002","2.0",List.of("purpose")),rule("R004","1.0",List.of())));
  assertEquals("ready",s.status());
  assertEquals(1,s.candidates().size());
  assertEquals("R002",s.selected().citation().code());
 }
 @Test void onlyGuidanceMeansMissing(){
  assertEquals("rule_missing",Rules.selection(List.of(rule("R001","1.0",List.of()))).status());
 }
 @Test void differingCompletenessRulesStillConflict(){
  assertEquals("rule_conflict",Rules.selection(List.of(rule("A","1",List.of("purpose")),rule("B","1",List.of("note")))).status());
 }
 @Test void amountThresholdIsInclusive(){
  var r003=rule("R003","1.0",List.of("purpose"),100000L);
  assertEquals(List.of(),Rules.requiredFor(r003,"99999"));
  assertEquals(List.of("purpose"),Rules.requiredFor(r003,"100000"));
  assertEquals(List.of("purpose"),Rules.requiredFor(r003,"100001"));
  assertEquals(List.of("purpose"),Rules.requiredFor(r003,null));
 }
 @Test void noThresholdAppliesToEveryInvoice(){
  var r002=rule("R002","2.0",List.of("purpose"));
  assertEquals(List.of("purpose"),Rules.requiredFor(r002,"1"));
  assertEquals(List.of("purpose"),Rules.requiredFor(r002,null));
 }
}
