package main
import ("strings"; "testing")
func TestBasicUnicode(t *testing.T) { b,e:=BuildFeedbackEmail("user@example.com","support@company.com","张三","产品建议","希望增加夜间模式功能"); if e!=nil || !strings.Contains(b,"张三") || !strings.Contains(b,"产品建议") || !strings.Contains(b,"希望增加夜间模式功能") || !strings.Contains(b,"text/html") { t.Fatalf("valid feedback was not preserved: %v %q",e,b) } }
func TestBadAddress(t *testing.T) { if _,e:=BuildFeedbackEmail("bad","support@example.com","u","s","f"); e==nil { t.Fatal("invalid sender accepted") } }
