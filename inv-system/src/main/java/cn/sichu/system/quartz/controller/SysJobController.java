package cn.sichu.system.quartz.controller;

import cn.sichu.system.quartz.entity.SysJob;
import cn.sichu.system.quartz.service.ISysJobService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;
import result.Result;

/**
 * @author sichu huang
 * @since 2025/12/07 02:50
 */
@RestController
@RequestMapping("/api/quartz")
@RequiredArgsConstructor
@Slf4j
public class SysJobController {

    private final ISysJobService sysJobService;

    /**
     * 新增定时任务
     *
     * @param job SysJob
     * @return result.Result<java.lang.Void>
     * @author sichu huang
     * @since 2025/12/07 19:22:03
     */
    @PostMapping("/add")
    public Result<Void> add(@RequestBody SysJob job) {
        sysJobService.saveJob(job);
        return Result.success();
    }

    /**
     * 更新定时任务
     *
     * @param job SysJob
     * @return result.Result<java.lang.Void>
     * @author sichu huang
     * @since 2025/12/07 19:22:25
     */
    @PostMapping("/update")
    public Result<Void> update(@RequestBody SysJob job) {
        sysJobService.updateJob(job);
        return Result.success();
    }

    /**
     * 启用/暂停任务
     *
     * @param id     id
     * @param status status
     * @return result.Result<java.lang.Void>
     * @author sichu huang
     * @since 2025/12/07 19:22:53
     */
    @PostMapping("/changeStatus")
    public Result<Void> changeStatus(@RequestParam("id") Long id,
        @RequestParam("status") Integer status) {
        sysJobService.changeStatus(id, status);
        return Result.success();
    }

    /**
     * 立即执行一次任务
     *
     * @param id id
     * @return result.Result<java.lang.Void>
     * @author sichu huang
     * @since 2025/12/07 19:23:15
     */
    @PostMapping("/runOnce")
    public Result<Void> runOnce(@RequestParam("id") Long id) {
        sysJobService.runOnce(id);
        return Result.success();
    }

    /**
     * 批量删除任务(逻辑删除)
     *
     * @param ids ids
     * @return result.Result<java.lang.Void>
     * @author sichu huang
     * @since 2025/12/07 19:23:59
     */
    @PostMapping("/remove")
    public Result<Void> remove(@RequestBody Long[] ids) {
        sysJobService.removeJobByIds(ids);
        return Result.success();
    }
}
