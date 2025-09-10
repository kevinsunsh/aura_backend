package tool

import (
	"aura-backend/internal/logger"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
)

// PythonWrapper 使用系统调用调用 Python VAD 引擎
type PythonWrapper struct {
	pythonPath  string
	scriptPath  string
	initialized bool
	mutex       sync.Mutex
}

type PythonResult struct {
	Success bool
	Data    interface{}
	Error   string
}

var (
	pyOnce sync.Once
)

// NewPythonWrapper 初始化Python包装器
func NewPythonWrapper() *PythonWrapper {
	pw := &PythonWrapper{}

	// 查找Python可执行文件
	pythonPath, err := exec.LookPath("python3")
	if err != nil {
		logger.Log.Errorf("找不到python3: %v", err)
		return nil
	}
	pw.pythonPath = pythonPath

	// 设置脚本路径
	exePath, _ := os.Executable()
	exeDir := filepath.Dir(exePath)
	pw.scriptPath = filepath.Join(exeDir, "internal", "tool", "vad_engine.py")

	// 检查脚本是否存在
	if _, err := os.Stat(pw.scriptPath); os.IsNotExist(err) {
		logger.Log.Errorf("Python脚本不存在: %s", pw.scriptPath)
		return nil
	}

	pw.initialized = true
	logger.Log.Info("Python包装器初始化成功 (系统调用)")
	return pw
}

// CallPythonFunction 统一分发
func (pw *PythonWrapper) CallPythonFunction(function string, args ...interface{}) (*PythonResult, error) {
	pw.mutex.Lock()
	defer pw.mutex.Unlock()

	if !pw.initialized {
		return &PythonResult{Success: false, Error: "python wrapper 未初始化"}, fmt.Errorf("python wrapper 未初始化")
	}

	switch function {
	case "start_vad_engine":
		return pw.startVADEngine(args...)
	case "stop_vad_engine":
		return pw.stopVADEngine()
	case "process_audio_chunk":
		return pw.processAudioChunk(args...)
	default:
		return &PythonResult{Success: false, Error: fmt.Sprintf("未知函数: %s", function)}, fmt.Errorf("未知函数: %s", function)
	}
}

func (pw *PythonWrapper) startVADEngine(args ...interface{}) (*PythonResult, error) {
	// 可选: model_path 参数
	var modelPath string
	if len(args) > 0 {
		if s, ok := args[0].(string); ok {
			modelPath = s
		}
	}

	// 构建命令参数
	cmdArgs := []string{pw.scriptPath, "start_vad_engine"}
	if modelPath != "" {
		cmdArgs = append(cmdArgs, modelPath)
	}

	// 执行Python脚本
	cmd := exec.Command(pw.pythonPath, cmdArgs...)
	output, err := cmd.Output()
	if err != nil {
		return &PythonResult{Success: false, Error: fmt.Sprintf("执行Python脚本失败: %v", err)}, nil
	}

	// 解析输出
	var result PythonResult
	if err := json.Unmarshal(output, &result); err != nil {
		return &PythonResult{Success: false, Error: fmt.Sprintf("解析Python输出失败: %v", err)}, nil
	}

	return &result, nil
}

func (pw *PythonWrapper) stopVADEngine() (*PythonResult, error) {
	// 构建命令参数
	cmdArgs := []string{pw.scriptPath, "stop_vad_engine"}

	// 执行Python脚本
	cmd := exec.Command(pw.pythonPath, cmdArgs...)
	output, err := cmd.Output()
	if err != nil {
		return &PythonResult{Success: false, Error: fmt.Sprintf("执行Python脚本失败: %v", err)}, nil
	}

	// 解析输出
	var result PythonResult
	if err := json.Unmarshal(output, &result); err != nil {
		return &PythonResult{Success: false, Error: fmt.Sprintf("解析Python输出失败: %v", err)}, nil
	}

	return &result, nil
}

func (pw *PythonWrapper) processAudioChunk(args ...interface{}) (*PythonResult, error) {
	if len(args) < 1 {
		return &PythonResult{Success: false, Error: "缺少音频数据参数"}, nil
	}
	audio, ok := args[0].([]byte)
	if !ok {
		return &PythonResult{Success: false, Error: "音频数据类型必须为 []byte"}, nil
	}

	// 构建命令参数
	cmdArgs := []string{pw.scriptPath, "process_audio_chunk"}

	// 将音频数据编码为base64传递给Python脚本
	audioData := fmt.Sprintf("%x", audio) // 简单的十六进制编码
	cmdArgs = append(cmdArgs, audioData)

	// 执行Python脚本
	cmd := exec.Command(pw.pythonPath, cmdArgs...)
	output, err := cmd.Output()
	if err != nil {
		return &PythonResult{Success: false, Error: fmt.Sprintf("执行Python脚本失败: %v", err)}, nil
	}

	// 解析输出
	var result PythonResult
	if err := json.Unmarshal(output, &result); err != nil {
		return &PythonResult{Success: false, Error: fmt.Sprintf("解析Python输出失败: %v", err)}, nil
	}

	return &result, nil
}
